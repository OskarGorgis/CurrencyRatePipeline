"""Tests for ingest_bronze.py: quarter partitioning, landing, and bronze table build."""
import json
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

import config
import ingest_bronze
from ingest_bronze import (
    build_bronze_table,
    iter_quarters,
    land_quarter,
    main,
    quarter_bounds,
    raw_path,
    run,
)
from nbp_client import NbpApiError, NoDataForRange


class FrozenDate(date):
    _today = date(2026, 8, 15)

    @classmethod
    def today(cls):
        return cls._today


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(ingest_bronze, "date", FrozenDate)
    return FrozenDate._today


@pytest.fixture
def tmp_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(config, "BRONZE_ROOT", tmp_path / "bronze")
    return tmp_path


# --- quarter_bounds -------------------------------------------------

def test_quarter_bounds_mid_quarter():
    assert quarter_bounds(date(2024, 2, 15)) == (date(2024, 1, 1), date(2024, 3, 31))


def test_quarter_bounds_q4_year_boundary():
    assert quarter_bounds(date(2024, 12, 25)) == (date(2024, 10, 1), date(2024, 12, 31))


def test_quarter_bounds_leap_year_q1():
    assert quarter_bounds(date(2024, 3, 1)) == (date(2024, 1, 1), date(2024, 3, 31))


# --- iter_quarters ----------------------------------------------------

def test_iter_quarters_single_quarter(frozen_today):
    result = list(iter_quarters(date(2024, 1, 1), date(2024, 2, 29)))
    assert result == [(date(2024, 1, 1), date(2024, 3, 31), "2024Q1")]


def test_iter_quarters_spans_multiple_quarters(frozen_today):
    result = list(iter_quarters(date(2024, 1, 15), date(2024, 5, 1)))
    labels = [label for _, _, label in result]
    assert labels == ["2024Q1", "2024Q2"]


def test_iter_quarters_overlapping_requests_agree_on_shared_quarter(frozen_today):
    """Regression: two different requested ranges must produce identical
    bounds for any quarter they both cover (the 'two sources of truth' bug)."""
    a = list(iter_quarters(date(2024, 1, 1), date(2024, 2, 29)))
    b = list(iter_quarters(date(2024, 1, 15), date(2024, 5, 1)))

    a_q1 = next(x for x in a if x[2] == "2024Q1")
    b_q1 = next(x for x in b if x[2] == "2024Q1")
    assert a_q1 == b_q1


def test_iter_quarters_rejects_inverted_range(frozen_today):
    with pytest.raises(ValueError):
        list(iter_quarters(date(2024, 2, 1), date(2024, 1, 1)))


def test_iter_quarters_rejects_start_before_earliest(frozen_today):
    with pytest.raises(ValueError):
        list(iter_quarters(date(1999, 1, 1), date(2000, 1, 1)))


def test_iter_quarters_rejects_end_in_future(frozen_today):
    with pytest.raises(ValueError):
        list(iter_quarters(date(2020, 1, 1), date(2030, 1, 1)))


def test_iter_quarters_clips_open_quarter_to_today(frozen_today):
    result = list(iter_quarters(date(2026, 7, 1), date(2026, 8, 15)))
    assert result == [(date(2026, 7, 1), date(2026, 8, 15), "2026Q3")]


# --- raw_path / land_quarter -------------------------------------------

def test_raw_path(tmp_tables):
    assert raw_path("2024Q1") == config.RAW_ROOT / "2024Q1.json"


def test_land_quarter_skips_if_already_landed_and_not_forced(tmp_tables):
    client = MagicMock()
    out_path = raw_path("2024Q1")
    out_path.parent.mkdir(parents=True)
    out_path.write_text("{}", encoding="utf-8")

    land_quarter(client, date(2024, 1, 1), date(2024, 3, 31), "2024Q1", force=False)

    client.fetch_rates.assert_not_called()


def test_land_quarter_refetches_when_forced(tmp_tables):
    client = MagicMock()
    client.fetch_rates.return_value = [{"effectiveDate": "2024-01-02", "rates": []}]
    out_path = raw_path("2024Q1")
    out_path.parent.mkdir(parents=True)
    out_path.write_text("{}", encoding="utf-8")

    land_quarter(client, date(2024, 1, 1), date(2024, 3, 31), "2024Q1", force=True)

    client.fetch_rates.assert_called_once()
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["quarter"] == "2024Q1"
    assert envelope["payload"] == [{"effectiveDate": "2024-01-02", "rates": []}]


def test_land_quarter_handles_no_data(tmp_tables):
    client = MagicMock()
    client.fetch_rates.side_effect = NoDataForRange("empty")

    land_quarter(client, date(2024, 1, 1), date(2024, 3, 31), "2024Q1")

    assert not raw_path("2024Q1").exists()


def test_land_quarter_handles_api_error(tmp_tables):
    client = MagicMock()
    client.fetch_rates.side_effect = NbpApiError("boom")

    land_quarter(client, date(2024, 1, 1), date(2024, 3, 31), "2024Q1")

    assert not raw_path("2024Q1").exists()


# --- run(): open-quarter force logic ------------------------------------

def test_run_forces_open_quarter_even_without_force_flag(tmp_tables, frozen_today, monkeypatch):
    fake_client = MagicMock()
    fake_client.fetch_rates.return_value = [{"effectiveDate": "2026-08-01", "rates": []}]
    monkeypatch.setattr(ingest_bronze, "NbpClient", lambda: fake_client)

    run(date(2026, 8, 1), date(2026, 8, 15), force=False)
    assert fake_client.fetch_rates.call_count == 1

    # Still an open quarter on the second run - re-fetched even without --force.
    run(date(2026, 8, 1), date(2026, 8, 15), force=False)
    assert fake_client.fetch_rates.call_count == 2


def test_run_skips_closed_quarter_without_force(tmp_tables, frozen_today, monkeypatch):
    fake_client = MagicMock()
    fake_client.fetch_rates.return_value = [{"effectiveDate": "2024-01-02", "rates": []}]
    monkeypatch.setattr(ingest_bronze, "NbpClient", lambda: fake_client)

    run(date(2024, 1, 1), date(2024, 3, 31), force=False)
    assert fake_client.fetch_rates.call_count == 1

    run(date(2024, 1, 1), date(2024, 3, 31), force=False)
    assert fake_client.fetch_rates.call_count == 1  # closed quarter, already landed -> skip


# --- _load_raw_records conflict resolution -------------------------------

def _write_raw(path, quarter, ingested_at, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "ingested_at_utc": ingested_at,
            "source": "nbp_api",
            "quarter": quarter,
            "requested_start": "2024-01-01",
            "requested_end": "2024-01-05",
            "payload": payload,
        }),
        encoding="utf-8",
    )


def test_load_raw_records_resolves_conflicts_by_newest_ingestion(tmp_tables):
    older = raw_path("2024Q1")
    _write_raw(older, "2024Q1", "2024-01-10T00:00:00+00:00", [
        {"effectiveDate": "2024-01-02", "rates": [{"code": "USD", "mid": 4.0}]},
    ])
    # Simulate a leftover file from the old naming scheme covering the same date.
    legacy = config.RAW_ROOT / "2024-01-01_2024-01-05.json"
    _write_raw(legacy, "legacy", "2024-01-11T00:00:00+00:00", [
        {"effectiveDate": "2024-01-02", "rates": [{"code": "USD", "mid": 4.2}]},
    ])

    records = ingest_bronze._load_raw_records()

    assert len(records) == 1
    assert records[0]["mid"] == 4.2


def test_build_bronze_table_is_long_format(tmp_tables):
    _write_raw(raw_path("2024Q1"), "2024Q1", "2024-01-10T00:00:00+00:00", [
        {"effectiveDate": "2024-01-02", "rates": [
            {"code": "USD", "mid": 4.0}, {"code": "EUR", "mid": 4.3},
        ]},
    ])

    out_path = build_bronze_table()
    df = pd.read_parquet(out_path)

    assert list(df.columns) == ["date", "currency", "mid"]
    assert len(df) == 2
    assert set(df["currency"]) == {"USD", "EUR"}


def test_build_bronze_table_empty_when_no_raw_files(tmp_tables):
    out_path = build_bronze_table()
    df = pd.read_parquet(out_path)
    assert df.empty
    assert list(df.columns) == ["date", "currency", "mid"]


# --- CLI (main) -----------------------------------------------------

def test_main_rejects_malformed_start_date(tmp_tables):
    assert main(["--start-date", "not-a-date"]) == 1


def test_main_rejects_inverted_range(tmp_tables):
    exit_code = main(["--start-date", "2030-01-01", "--end-date", "2020-01-01"])
    assert exit_code == 1


def test_main_requires_start_date(tmp_tables):
    with pytest.raises(SystemExit):
        main([])
