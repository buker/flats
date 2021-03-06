""""
Pipeline to concatinate and dedup all scraping outputs.
"""
import os
import logging
import datetime

import pandas as pd

import pipelines.utils as utils
from common import (
    RAW_DATA_PATH,
    CONCATED_DATA_PATH,
    select_newest_date,
)
import columns
from s3_client import s3_client

log = logging.getLogger(__name__)

# skip concating memory heavy columns
COLUMNS_TO_SKIP = (columns.DESC, columns.IMAGE_LINK)


s3_client = s3_client()

def concat_data_task(data_type):
    log.info("Starting data concatination task...")
    concat_csvs_to_parquet(data_type, columns_to_skip=COLUMNS_TO_SKIP)
    log.info(f"Finished concating files for {data_type}.")
    log.info("Finished concatination task.")


def concat_csvs_to_parquet(data_type, columns_to_skip):
    """
    Concat all raw csv files and save them as parquet skipping selected cols.
    """
    raw_paths = get_unconcated_raw_paths(data_type)
    if len(raw_paths) == 0:
        log.info("No files to concat. Skipping")
        return None
    raw_df = concat_dfs(raw_paths, columns_to_skip=columns_to_skip)

    previous_concated_df = s3_client.read_newest_df_from_s3(
        CONCATED_DATA_PATH, dtype=data_type
    )
    if previous_concated_df is not None:
        log.info(f"Previous concated df shape: {previous_concated_df.shape}")

        full_df = pd.concat([raw_df, previous_concated_df], sort=True)
        full_df = full_df.drop_duplicates(columns.OFFER_ID, keep="last")
        log.info(f"New concated df shape: {full_df.shape}")
        if full_df.shape == previous_concated_df.shape:
            log.info(
                "New concated file has the same number of records - not sending an update to s3"
            )
            return None
    else:
        log.info('Did not find any concated files. Creating new cocnated file.')
        full_df = raw_df
        log.info(f'New concated df shape: {full_df.shape}')

    s3_client.upload_df_to_s3_with_timestamp(full_df,
                                             s3_path=CONCATED_DATA_PATH,
                                             keyword='concated',
                                             dtype=data_type,
                                             extension='csv',
                                             )


def get_unconcated_raw_paths(data_type):
    """Returns paths of raw files newer than last concat date"""
    concated_paths = s3_client.list_s3_dir(CONCATED_DATA_PATH.format(data_type=data_type))
    raw_paths = s3_client.list_s3_dir(RAW_DATA_PATH.format(data_type=data_type))

    last_concat_date = select_newest_date(concated_paths)
    if last_concat_date is None:
        last_concat_date = datetime.datetime(2000, 1, 1)
    log.info(f'Will concat raw files newer than {last_concat_date}')
    # skip datetimes with invalid format
    raw_paths = [r for r in raw_paths if s3_client.get_date_from_filename(r) is not None]
    # skip raw files covered in previous concatination step
    raw_paths = [r for r in raw_paths if s3_client.get_date_from_filename(r) > last_concat_date]
    log.info(f'Found {len(raw_paths)} raw files newer than previous concat date')
    return raw_paths


def concat_dfs(paths, columns_to_skip):
    """
    Concat all files and drop all duplicates.
    """
    dfs = []
    for s3_path in paths:
        df = s3_client.read_df_from_s3(s3_path, columns_to_skip=columns_to_skip)
        dfs.append(df)
    log.info("Concatinating raw dfs ...")
    concatinated_df = pd.concat(dfs, sort=True).drop_duplicates(keep="last")
    return concatinated_df
