"""
Client for the NBP (National Bank of Poland) exchange rates Web API.

Encapsulates HTTP communication and retry/backoff logic. Date-range
partitioning into API-sized chunks (the NBP API rejects date ranges
longer than MAX_RANGE_DAYS) lives in ingest_bronze.py, not here.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional
import requests
import config

logger = logging.getLogger(__name__)


class NbpApiError(Exception):
    """Raised for non-retryable / unrecoverable NBP API errors."""


class NoDataForRange(Exception):
    """Raised when NBP returns 404 - no quotations in the requested range
    (e.g. the range is fully covered by holidays)."""


@dataclass(frozen=True)
class NbpClientConfig:
    table: str = "a"
    timeout_seconds: float = 10.0
    max_retries: int = 4
    backoff_base_seconds: float = 1.5


class NbpClient:
    """Thin, retrying HTTP client for the NBP exchange rates endpoint."""

    def __init__(
        self,
        client_config: Optional[NbpClientConfig] = None,
        session: Optional[requests.Session] = None,
    ):
        self.config = client_config or NbpClientConfig()
        self.session = session or requests.Session()

    def fetch_rates(self, start_date: date, end_date: date) -> dict:
        """Fetch raw NBP JSON for one date sub-range.

        Callers must split ranges longer than MAX_RANGE_DAYS themselves.
        """
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        
        if (end_date - start_date).days + 1 > config.MAX_RANGE_DAYS:
            raise ValueError(
                f"Date range {start_date}..{end_date} exceeds "
                f"max {config.MAX_RANGE_DAYS} days"
            )
        
        url = (
            f"{config.NBP_API_URL}/{self.config.table}/{start_date.isoformat()}/{end_date.isoformat()}/"
        )
        params = {"format": "json"}

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                print(f"Fetching {url} (attempt {attempt})")
                response = self.session.get(url, params=params, timeout=self.config.timeout_seconds)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "Network error fetching %s [%s..%s], attempt %d/%d: %s",
                    url, start_date, end_date, attempt, self.config.max_retries, exc,
                )
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    # json.JSONDecodeError (and requests' own JSONDecodeError)
                    # both subclass ValueError - treat a 200 with an
                    # unparsable body as a permanent failure, not a crash.
                    raise NbpApiError(
                        f"NBP API returned malformed JSON for [{start_date}..{end_date}]: {exc}"
                    ) from exc

            if response.status_code == 404:
                raise NoDataForRange(
                    f"No data in range {start_date}..{end_date}"
                )

            if response.status_code in config.RETRYABLE_STATUS_CODES:
                logger.warning(
                    "Retryable HTTP %d for %s [%s..%s], attempt %d/%d",
                    response.status_code, url, start_date, end_date,
                    attempt, self.config.max_retries,
                )
                self._sleep_backoff(attempt)
                continue

            # Non-retryable, e.g. 400 Bad Request -> fail loudly, don't hide it
            raise NbpApiError(
                f"NBP API returned {response.status_code}"
                f"[{start_date}..{end_date}]: {response.text[:200]}"
            )

        raise NbpApiError(
            f"Exhausted retries fetching [{start_date}..{end_date}]"
        ) from last_exc

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(self.config.backoff_base_seconds ** attempt)