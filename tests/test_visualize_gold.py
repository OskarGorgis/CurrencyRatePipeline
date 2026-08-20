"""Tests for visualize_gold.py: chart rendering and question-answering insights."""
import pandas as pd
import pytest

import config
from visualize_gold import build_charts, compute_insights, print_insights, run


@pytest.fixture
def tmp_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GOLD_ROOT", tmp_path / "gold")
    monkeypatch.setattr(config, "CHARTS_ROOT", tmp_path / "charts")
    return tmp_path


def _gold_df(rows):
    return pd.DataFrame(rows, columns=["date", "currency", "mid", "daily_change", "daily_change_pct"])


def _write_gold(rows):
    config.GOLD_ROOT.mkdir(parents=True, exist_ok=True)
    _gold_df(rows).to_parquet(config.GOLD_ROOT / "rates.parquet", index=False)


def _sample_rows():
    # Three days per currency: base, +10% (biggest rise), then -18.18% off
    # that peak (biggest fall) - same shape for every currency so the
    # extremes land on the same dates, only the price level differs.
    rows = []
    for currency, base in [("EUR", 4.3), ("USD", 4.0), ("GBP", 5.0), ("JPY", 0.03)]:
        rows.append((pd.Timestamp("2024-01-02"), currency, base, None, None))
        rows.append((pd.Timestamp("2024-01-03"), currency, base * 1.1, base * 0.1, 10.0))
        rows.append((pd.Timestamp("2024-01-04"), currency, base * 0.9, base * -0.2, -18.18))
    return rows


def test_build_charts_creates_jpg_files(tmp_tables):
    _write_gold(_sample_rows())
    paths = build_charts()
    assert len(paths) == 2
    for path in paths:
        assert path.exists()
        assert path.suffix == ".jpg"
        assert path.stat().st_size > 0


def test_build_charts_raises_clear_error_when_gold_missing(tmp_tables):
    with pytest.raises(FileNotFoundError, match="ingest_gold"):
        build_charts()


def test_compute_insights_finds_extremes():
    gold = _gold_df(_sample_rows())
    insights = compute_insights(gold)

    usd = insights[insights["currency"] == "USD"].iloc[0]
    assert usd["lowest_value"] == pytest.approx(3.6, abs=0.01)
    assert usd["highest_value"] == pytest.approx(4.4, abs=0.01)
    assert usd["biggest_one_day_rise_pct"] == pytest.approx(10.0)
    assert usd["biggest_one_day_fall_pct"] == pytest.approx(-18.18, abs=0.01)


def test_compute_insights_skips_currency_with_no_data():
    gold = _gold_df(_sample_rows())
    gold = gold[gold["currency"] != "JPY"]  # simulate a currency with nothing landed

    insights = compute_insights(gold)

    assert "JPY" not in set(insights["currency"])
    assert set(insights["currency"]) == {"EUR", "USD", "GBP"}


def test_compute_insights_handles_single_data_point():
    gold = _gold_df([(pd.Timestamp("2024-01-02"), "USD", 4.0, None, None)])
    insights = compute_insights(gold)

    row = insights.iloc[0]
    assert row["lowest_value"] == pytest.approx(4.0)
    assert row["biggest_one_day_fall_date"] is None
    assert row["biggest_one_day_rise_date"] is None


def test_print_insights_reports_missing_daily_change(capsys):
    gold = _gold_df([(pd.Timestamp("2024-01-02"), "USD", 4.0, None, None)])
    print_insights(compute_insights(gold))
    captured = capsys.readouterr()
    assert "not enough data" in captured.out


def test_print_insights_handles_empty_dataframe(capsys):
    print_insights(pd.DataFrame())
    captured = capsys.readouterr()
    assert "No insights available" in captured.out


def test_run_end_to_end_produces_charts_and_prints_insights(tmp_tables, capsys):
    _write_gold(_sample_rows())
    run()

    captured = capsys.readouterr()
    assert "USD/PLN" in captured.out
    assert (config.CHARTS_ROOT / "dynamics_by_currency.jpg").exists()
    assert (config.CHARTS_ROOT / "dynamics_indexed.jpg").exists()
