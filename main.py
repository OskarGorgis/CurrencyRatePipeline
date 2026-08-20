"""
Pipeline orchestrator: runs bronze -> silver -> gold -> charts end to end,
in one of two modes.

full mode:  re-ingest from Jan 1 of --year (default 2025) through today
            (closed quarters already landed are skipped, per
            ingest_bronze's normal idempotency), then rebuild
            silver/gold and regenerate charts/insights.
daily mode: refresh only yesterday's data. Under the hood this still
            goes through ingest_bronze.run(), but since landing happens
            at quarter granularity (see ingest_bronze.iter_quarters),
            "yesterday" resolves to the quarter containing it - which
            is a no-op if that quarter is already closed and fully
            landed, or a re-fetch of the currently open quarter if not.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from typing import List, Optional

import config
import ingest_bronze
import ingest_gold
import ingest_silver
import visualize_gold

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _rebuild_and_report() -> None:
    ingest_bronze.build_bronze_table()
    ingest_silver.build_silver_table()
    ingest_gold.build_gold_table()
    visualize_gold.run()


def run_full(year: int) -> None:
    start = date(year, 1, 1)
    end = date.today()
    logger.info("FULL update: ingesting %s..%s", start, end)
    ingest_bronze.run(start, end)
    _rebuild_and_report()


def run_daily() -> None:
    yesterday = date.today() - timedelta(days=1)
    logger.info("DAILY update: ingesting %s", yesterday)
    ingest_bronze.run(yesterday, yesterday)
    _rebuild_and_report()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the currency rate pipeline: bronze -> silver -> gold -> charts.")
    parser.add_argument(
        "--mode", choices=["full", "daily"], default="full",
        help="full: ingest from --year through today. daily: refresh only yesterday's data. Default: full.",
    )
    parser.add_argument(
        "--year", type=int, default=None,
        help=f"Start year for --mode full (default: {config.DEFAULT_YEAR}). Ignored in --mode daily.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.mode == "daily" and args.year is not None:
        logger.warning("--year is ignored in --mode daily")

    try:
        if args.mode == "full":
            year = args.year if args.year is not None else config.DEFAULT_YEAR
            earliest_year = config.NBP_EARLIEST_DATE.year
            latest_year = date.today().year
            if not (earliest_year <= year <= latest_year):
                logger.error(
                    "--year %d is out of range - must be between %d and %d",
                    year, earliest_year, latest_year,
                )
                return 1
            run_full(year)
        else:
            run_daily()
    except (ValueError, FileNotFoundError) as exc:
        logger.error("Pipeline run failed: %s", exc)
        return 1

    logger.info("Pipeline run finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
