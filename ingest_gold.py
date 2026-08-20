"""
Gold-layer aggregation: takes the wide-format silver table and builds a
long-format analysis table for the four PLN-quoted currencies this
pipeline reports on (EUR, USD, GBP, JPY), adding the day-over-day
change in mid rate (both absolute and percentage).

"Day-over-day" means change versus the previous *published* NBP
quotation, not the previous calendar day - NBP does not publish on
weekends/holidays, so across a long weekend this is a multi-day gap.
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

TARGET_CURRENCIES = ["EUR", "USD", "GBP", "JPY"]


def build_gold_table() -> Path:
    """Rebuild the gold analysis table from the current silver table."""
    silver_path = config.SILVER_ROOT / "rates.parquet"
    if not silver_path.exists():
        raise FileNotFoundError(
            f"Silver table not found at {silver_path} - run ingest_silver.py "
            "(or ingest_silver.build_silver_table()) first."
        )
    wide = pd.read_parquet(silver_path)

    missing = [c for c in TARGET_CURRENCIES if c not in wide.columns]
    if missing:
        raise ValueError(f"Silver table is missing expected currencies: {missing}")

    wide = wide[["date"] + TARGET_CURRENCIES].sort_values("date").reset_index(drop=True)

    per_currency = []
    for currency in TARGET_CURRENCIES:
        series = wide[["date", currency]].rename(columns={currency: "mid"})
        series["currency"] = currency
        series["daily_change"] = series["mid"].diff()
        series["daily_change_pct"] = series["mid"].pct_change() * 100
        per_currency.append(series)

    gold = pd.concat(per_currency, ignore_index=True)
    gold = gold[["date", "currency", "mid", "daily_change", "daily_change_pct"]]
    gold = gold.sort_values(["currency", "date"]).reset_index(drop=True)

    config.GOLD_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = config.GOLD_ROOT / "rates.parquet"
    gold.to_parquet(out_path, index=False)
    logger.info("Gold table rebuilt: %d rows -> %s", len(gold), out_path)
    return out_path


if __name__ == "__main__":
    build_gold_table()
