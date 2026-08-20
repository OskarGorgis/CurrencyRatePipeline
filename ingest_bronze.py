"""
Bronze-layer ingestion: pulls raw exchange-rate data from the NBP API.

raw    - landing zone for unmodified JSON, one file per calendar quarter
         (tables/raw/{quarter}.json), keyed by quarter regardless of the
         date range that was actually requested
bronze - long-format parquet table (date, currency, mid), rebuilt from
         scratch from every landed raw file each time build_bronze_table()
         runs

Design goals:
- idempotent   - re-running does not re-fetch quarters already landed,
                 except the currently open quarter which is always
                 re-fetched since new rows can still arrive for it
- traceable    - every landed file carries ingestion metadata (when/how
                 it was fetched), so bronze-table construction and
                 silver-layer processing have full lineage back to the
                 source
- resilient    - transient API/network errors are retried by the client;
                 a permanent failure for one quarter is logged and
                 skipped, it does not abort the whole run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import pandas as pd

import config
from nbp_client import NbpApiError, NbpClient, NoDataForRange

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def quarter_bounds(d: date) -> Tuple[date, date]:
    """Return the (start, end) of the calendar quarter containing `d`."""
    start_month = ((d.month - 1) // 3) * 3 + 1
    q_start = date(d.year, start_month, 1)
    if start_month == 10:
        q_end = date(d.year, 12, 31)
    else:
        q_end = date(d.year, start_month + 3, 1) - timedelta(days=1)
    return q_start, q_end


def iter_quarters(start_date: date, end_date: date) -> Iterator[Tuple[date, date, str]]:
    """Yield full calendar quarters covering [start_date, end_date].

    Bounds are clipped only to config.NBP_EARLIEST_DATE and date.today(),
    never to start_date/end_date - two overlapping requests must produce
    identical bounds for any quarter they share.
    """
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if start_date < config.NBP_EARLIEST_DATE:
        raise ValueError(
            f"start_date {start_date} is before earliest NBP data {config.NBP_EARLIEST_DATE}"
        )
    if end_date > date.today():
        raise ValueError(f"end_date {end_date} is in the future")
    if end_date < config.NBP_EARLIEST_DATE:
        raise ValueError(
            f"end_date {end_date} is before earliest NBP data {config.NBP_EARLIEST_DATE}"
        )

    today = date.today()
    q_start, _ = quarter_bounds(start_date)
    while q_start <= end_date:
        _, q_end = quarter_bounds(q_start)
        label = f"{q_start.year}Q{(q_start.month - 1) // 3 + 1}"

        clipped_start = max(q_start, config.NBP_EARLIEST_DATE)
        clipped_end = min(q_end, today)
        if clipped_start <= clipped_end:
            yield clipped_start, clipped_end, label

        q_start = q_end + timedelta(days=1)


def raw_path(quarter_label: str) -> Path:
    return config.RAW_ROOT / f"{quarter_label}.json"


def land_quarter(
    client: NbpClient, start: date, end: date, quarter_label: str, force: bool = False
) -> None:
    out_path = raw_path(quarter_label)

    if out_path.exists() and not force:
        logger.info("SKIP  [%s] (%s..%s) - already landed at %s", quarter_label, start, end, out_path)
        return

    try:
        payload = client.fetch_rates(start, end)
    except NoDataForRange:
        logger.warning("EMPTY [%s] (%s..%s) - no quotations in range, skipping", quarter_label, start, end)
        return
    except NbpApiError as exc:
        logger.error("FAIL  [%s] (%s..%s) - %s", quarter_label, start, end, exc)
        return

    envelope = {
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "nbp_api",
        "quarter": quarter_label,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "payload": payload,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("OK    [%s] (%s..%s) -> %s", quarter_label, start, end, out_path)


def run(start: date, end: date, force: bool = False) -> None:
    client = NbpClient()
    for q_start, q_end, label in iter_quarters(start, end):
        # The currently open quarter can still gain rows on later days,
        # so it's always re-fetched regardless of --force.
        is_open_quarter = q_end >= date.today()
        land_quarter(client, q_start, q_end, label, force=(force or is_open_quarter))


def _load_raw_records() -> List[dict]:
    """Load every landed raw file and flatten to one record per (date, currency).

    If two raw files disagree on the same (date, currency) - e.g. leftover
    files from an old naming scheme - the record from the file with the
    newer ingested_at_utc wins.
    """
    records: Dict[Tuple[str, str], dict] = {}

    for raw_file in sorted(config.RAW_ROOT.glob("*.json")):
        envelope = json.loads(raw_file.read_text(encoding="utf-8"))
        ingested_at = envelope["ingested_at_utc"]
        for table_entry in envelope["payload"]:
            record_date = table_entry["effectiveDate"]
            for rate in table_entry["rates"]:
                key = (record_date, rate["code"])
                existing = records.get(key)
                if existing is None or ingested_at > existing["ingested_at_utc"]:
                    records[key] = {
                        "date": record_date,
                        "currency": rate["code"],
                        "mid": rate["mid"],
                        "ingested_at_utc": ingested_at,
                    }

    return list(records.values())


def build_bronze_table() -> Path:
    """Rebuild the bronze parquet table from scratch from every landed raw file.

    Long format: one row per (date, currency), columns date/currency/mid.
    """
    records = _load_raw_records()

    if records:
        df = pd.DataFrame(records)[["date", "currency", "mid"]]
        df = df.sort_values(["date", "currency"]).reset_index(drop=True)
    else:
        df = pd.DataFrame(columns=["date", "currency", "mid"])

    config.BRONZE_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = config.BRONZE_ROOT / "rates.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Bronze table rebuilt: %d rows -> %s", len(df), out_path)
    return out_path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Land raw NBP exchange rate data into the bronze layer.")
    parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD) for ingestion range")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD) for ingestion range", default=date.today().isoformat())
    parser.add_argument("--force", action="store_true", help="Re-fetch quarters even if already landed")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    try:
        start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    except ValueError as exc:
        logger.error("Invalid date - expected YYYY-MM-DD: %s", exc)
        return 1

    logger.info("Starting bronze ingestion range %s..%s", start, end)
    try:
        run(start, end, force=args.force)
    except ValueError as exc:
        logger.error("Invalid date range: %s", exc)
        return 1

    build_bronze_table()
    logger.info("Bronze ingestion finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
