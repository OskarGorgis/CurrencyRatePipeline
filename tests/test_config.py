"""Tests for config.py: constants and directory layout."""
from datetime import date

import config


def test_max_range_days_matches_nbp_limit():
    assert config.MAX_RANGE_DAYS == 93


def test_nbp_earliest_date():
    assert config.NBP_EARLIEST_DATE == date(2002, 1, 2)


def test_layer_roots_are_nested_under_tables_root():
    for root in (config.RAW_ROOT, config.BRONZE_ROOT, config.SILVER_ROOT, config.GOLD_ROOT):
        assert root.parent == config.TABLES_ROOT


def test_layer_roots_are_distinct():
    roots = [config.RAW_ROOT, config.BRONZE_ROOT, config.SILVER_ROOT, config.GOLD_ROOT, config.CHARTS_ROOT]
    assert len(roots) == len(set(roots))
