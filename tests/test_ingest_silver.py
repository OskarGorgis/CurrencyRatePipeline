"""Tests for ingest_silver.py: bronze (long) -> silver (wide) pivot."""
import pandas as pd
import pytest

import config
from ingest_silver import build_silver_table


@pytest.fixture
def tmp_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BRONZE_ROOT", tmp_path / "bronze")
    monkeypatch.setattr(config, "SILVER_ROOT", tmp_path / "silver")
    return tmp_path


def _write_bronze(rows):
    config.BRONZE_ROOT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["date", "currency", "mid"])
    df.to_parquet(config.BRONZE_ROOT / "rates.parquet", index=False)


def test_build_silver_table_pivots_to_wide_format(tmp_tables):
    _write_bronze([
        ("2024-01-02", "USD", 4.0),
        ("2024-01-02", "EUR", 4.3),
        ("2024-01-03", "USD", 4.1),
    ])

    out_path = build_silver_table()
    wide = pd.read_parquet(out_path)

    assert list(wide.columns) == ["date", "EUR", "USD"]
    assert len(wide) == 2
    row = wide[wide["date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert row["USD"] == 4.1
    assert pd.isna(row["EUR"])  # no EUR quote landed for this date - left as NaN, not filled


def test_build_silver_table_date_column_is_datetime(tmp_tables):
    _write_bronze([("2024-01-02", "USD", 4.0)])
    out_path = build_silver_table()
    wide = pd.read_parquet(out_path)
    assert pd.api.types.is_datetime64_any_dtype(wide["date"])


def test_build_silver_table_raises_clear_error_when_bronze_missing(tmp_tables):
    with pytest.raises(FileNotFoundError, match="ingest_bronze"):
        build_silver_table()
