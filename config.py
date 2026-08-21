from datetime import date
from pathlib import Path


NBP_API_URL = "https://api.nbp.pl/api/exchangerates/tables"
MAX_RANGE_DAYS = 93  # hard limit enforced by the NBP API
NBP_EARLIEST_DATE = date(2002, 1, 2)  # earliest date available in the NBP archive
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
TABLES_ROOT = Path("tables")
RAW_ROOT = TABLES_ROOT / "raw"
BRONZE_ROOT = TABLES_ROOT / "bronze"
SILVER_ROOT = TABLES_ROOT / "silver"
GOLD_ROOT = TABLES_ROOT / "gold"
CHARTS_ROOT = Path("charts")
DEFAULT_YEAR = 2021
TARGET_CURRENCIES = ["EUR", "USD", "GBP", "JPY"]