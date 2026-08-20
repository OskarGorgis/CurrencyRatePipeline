"""Tests for ingest_gold.py: silver (wide) -> gold (long + daily change) table."""
import pandas as pd
import pytest

import config
from ingest_gold import TARGET_CURRENCIES, build_gold_table


@pytest.fixture
def tmp_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SILVER_ROOT", tmp_path / "silver")
    monkeypatch.setattr(config, "GOLD_ROOT", tmp_path / "gold")
    return tmp_path


def _write_silver(rows, columns):
    config.SILVER_ROOT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=columns)
    df.to_parquet(config.SILVER_ROOT / "rates.parquet", index=False)


def test_build_gold_table_computes_daily_change(tmp_tables):
    _write_silver(
        [
            (pd.Timestamp("2024-01-02"), 4.0, 4.3, 5.0, 0.03),
            (pd.Timestamp("2024-01-03"), 4.2, 4.3, 5.0, 0.03),
        ],
        columns=["date", "USD", "EUR", "GBP", "JPY"],
    )

    out_path = build_gold_table()
    gold = pd.read_parquet(out_path)

    usd = gold[gold["currency"] == "USD"].sort_values("date").reset_index(drop=True)
    assert pd.isna(usd.loc[0, "daily_change"])  # first observation has no prior day
    assert usd.loc[1, "daily_change"] == pytest.approx(0.2)
    assert usd.loc[1, "daily_change_pct"] == pytest.approx(5.0, abs=0.01)


def test_build_gold_table_only_keeps_target_currencies(tmp_tables):
    _write_silver(
        [(pd.Timestamp("2024-01-02"), 4.0, 4.3, 5.0, 0.03, 10.0)],
        columns=["date", "USD", "EUR", "GBP", "JPY", "CHF"],
    )
    out_path = build_gold_table()
    gold = pd.read_parquet(out_path)
    assert set(gold["currency"]) == set(TARGET_CURRENCIES)


def test_build_gold_table_raises_on_missing_currency(tmp_tables):
    _write_silver(
        [(pd.Timestamp("2024-01-02"), 4.0, 4.3)],
        columns=["date", "USD", "EUR"],  # missing GBP, JPY
    )
    with pytest.raises(ValueError, match="GBP"):
        build_gold_table()


def test_build_gold_table_raises_clear_error_when_silver_missing(tmp_tables):
    with pytest.raises(FileNotFoundError, match="ingest_silver"):
        build_gold_table()
