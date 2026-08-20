"""
Silver-layer transformation: reshapes the long-format bronze table
(date, currency, mid) into a wide-format table - one column per
currency, one row per date - suitable for direct time-series analysis.

Missing values (weekends/holidays with no NBP quotation, or currencies
not tracked for the full date range) are left as NaN; no forward-fill
or interpolation happens here.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def build_silver_table() -> Path:
    """Rebuild the silver parquet table from the current bronze table."""
    bronze_path = config.BRONZE_ROOT / "rates.parquet"
    if not bronze_path.exists():
        raise FileNotFoundError(
            f"Bronze table not found at {bronze_path} - run ingest_bronze.py "
            "(or ingest_bronze.build_bronze_table()) first."
        )
    df = pd.read_parquet(bronze_path)
    df["date"] = pd.to_datetime(df["date"])

    wide = df.pivot(index="date", columns="currency", values="mid")
    wide.columns.name = None
    wide = wide.sort_index().reset_index()

    config.SILVER_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = config.SILVER_ROOT / "rates.parquet"
    wide.to_parquet(out_path, index=False)
    logger.info(
        "Silver table rebuilt: %d rows, %d currencies -> %s",
        len(wide), wide.shape[1] - 1, out_path,
    )
    return out_path


if __name__ == "__main__":
    build_silver_table()
