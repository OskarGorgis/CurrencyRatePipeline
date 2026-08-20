"""Tests for main.py: pipeline orchestration modes and CLI validation."""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

import config
import main as main_module


class FrozenDate(date):
    _today = date(2026, 8, 15)

    @classmethod
    def today(cls):
        return cls._today


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(main_module, "date", FrozenDate)
    return FrozenDate._today


@pytest.fixture
def mocked_stages(monkeypatch):
    mocks = {
        "run": MagicMock(),
        "build_bronze_table": MagicMock(),
        "build_silver_table": MagicMock(),
        "build_gold_table": MagicMock(),
        "viz_run": MagicMock(),
    }
    monkeypatch.setattr("ingest_bronze.run", mocks["run"])
    monkeypatch.setattr("ingest_bronze.build_bronze_table", mocks["build_bronze_table"])
    monkeypatch.setattr("ingest_silver.build_silver_table", mocks["build_silver_table"])
    monkeypatch.setattr("ingest_gold.build_gold_table", mocks["build_gold_table"])
    monkeypatch.setattr("visualize_gold.run", mocks["viz_run"])
    return mocks


def test_run_full_ingests_from_january_first_of_given_year(mocked_stages, frozen_today):
    main_module.run_full(2025)

    mocked_stages["run"].assert_called_once_with(date(2025, 1, 1), FrozenDate._today)
    mocked_stages["build_bronze_table"].assert_called_once()
    mocked_stages["build_silver_table"].assert_called_once()
    mocked_stages["build_gold_table"].assert_called_once()
    mocked_stages["viz_run"].assert_called_once()


def test_run_daily_ingests_only_yesterday(mocked_stages, frozen_today):
    main_module.run_daily()

    expected_yesterday = FrozenDate._today - timedelta(days=1)
    mocked_stages["run"].assert_called_once_with(expected_yesterday, expected_yesterday)


def test_main_defaults_to_full_mode_and_default_year(mocked_stages, frozen_today):
    exit_code = main_module.main([])
    assert exit_code == 0
    mocked_stages["run"].assert_called_once_with(
        date(config.DEFAULT_YEAR, 1, 1), FrozenDate._today
    )


def test_main_daily_mode_ignores_year_with_warning(mocked_stages, frozen_today, caplog):
    exit_code = main_module.main(["--mode", "daily", "--year", "2020"])
    assert exit_code == 0
    assert "ignored" in caplog.text.lower()


def test_main_rejects_year_before_nbp_earliest(mocked_stages, frozen_today):
    exit_code = main_module.main(["--mode", "full", "--year", "1999"])
    assert exit_code == 1
    mocked_stages["run"].assert_not_called()


def test_main_rejects_year_in_the_future(mocked_stages, frozen_today):
    exit_code = main_module.main(["--mode", "full", "--year", "2999"])
    assert exit_code == 1
    mocked_stages["run"].assert_not_called()


def test_main_rejects_unknown_mode():
    with pytest.raises(SystemExit):
        main_module.main(["--mode", "weekly"])


def test_main_returns_1_when_pipeline_raises_value_error(mocked_stages, frozen_today):
    mocked_stages["run"].side_effect = ValueError("boom")
    assert main_module.main([]) == 1


def test_main_returns_1_when_a_layer_file_is_missing(mocked_stages, frozen_today):
    mocked_stages["build_silver_table"].side_effect = FileNotFoundError("missing bronze")
    assert main_module.main([]) == 1
