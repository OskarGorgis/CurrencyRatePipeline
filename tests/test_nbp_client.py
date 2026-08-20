"""Tests for nbp_client.py: retry/backoff behavior and input validation."""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
import requests

import config
from nbp_client import NbpApiError, NbpClient, NbpClientConfig, NoDataForRange


class FakeResponse:
    def __init__(self, status_code, json_data=None, text="", json_error=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # Retry/backoff tests would otherwise really sleep between attempts.
    monkeypatch.setattr("nbp_client.time.sleep", lambda *_: None)


def make_client(session, max_retries=3):
    return NbpClient(client_config=NbpClientConfig(max_retries=max_retries), session=session)


def test_fetch_rates_rejects_inverted_range():
    client = make_client(MagicMock())
    with pytest.raises(ValueError):
        client.fetch_rates(date(2024, 2, 1), date(2024, 1, 1))


def test_fetch_rates_rejects_range_over_max_days():
    client = make_client(MagicMock())
    start = date(2024, 1, 1)
    end = start + timedelta(days=config.MAX_RANGE_DAYS)  # one day too many
    with pytest.raises(ValueError):
        client.fetch_rates(start, end)


def test_fetch_rates_accepts_range_at_exactly_max_days():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, json_data=[])
    client = make_client(session)
    start = date(2024, 1, 1)
    end = start + timedelta(days=config.MAX_RANGE_DAYS - 1)  # inclusive of both ends
    client.fetch_rates(start, end)  # must not raise


def test_fetch_rates_returns_json_on_200():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, json_data=[{"effectiveDate": "2024-01-02"}])
    client = make_client(session)

    result = client.fetch_rates(date(2024, 1, 1), date(2024, 1, 2))

    assert result == [{"effectiveDate": "2024-01-02"}]
    session.get.assert_called_once()


def test_fetch_rates_raises_no_data_on_404():
    session = MagicMock()
    session.get.return_value = FakeResponse(404)
    client = make_client(session)

    with pytest.raises(NoDataForRange):
        client.fetch_rates(date(2024, 1, 1), date(2024, 1, 2))


def test_fetch_rates_raises_api_error_on_400():
    session = MagicMock()
    session.get.return_value = FakeResponse(400, text="Bad Request")
    client = make_client(session)

    with pytest.raises(NbpApiError):
        client.fetch_rates(date(2024, 1, 1), date(2024, 1, 2))


def test_fetch_rates_retries_retryable_status_then_succeeds():
    session = MagicMock()
    session.get.side_effect = [
        FakeResponse(503),
        FakeResponse(200, json_data=[{"ok": True}]),
    ]
    client = make_client(session)

    result = client.fetch_rates(date(2024, 1, 1), date(2024, 1, 2))

    assert result == [{"ok": True}]
    assert session.get.call_count == 2


def test_fetch_rates_exhausts_retries_and_raises_api_error():
    session = MagicMock()
    session.get.return_value = FakeResponse(503)
    client = make_client(session, max_retries=3)

    with pytest.raises(NbpApiError):
        client.fetch_rates(date(2024, 1, 1), date(2024, 1, 2))

    assert session.get.call_count == 3


def test_fetch_rates_retries_network_errors_then_succeeds():
    session = MagicMock()
    session.get.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        FakeResponse(200, json_data=[{"ok": True}]),
    ]
    client = make_client(session)

    result = client.fetch_rates(date(2024, 1, 1), date(2024, 1, 2))

    assert result == [{"ok": True}]


def test_fetch_rates_raises_api_error_on_malformed_json():
    session = MagicMock()
    session.get.return_value = FakeResponse(200, json_error=ValueError("bad json"))
    client = make_client(session)

    with pytest.raises(NbpApiError):
        client.fetch_rates(date(2024, 1, 1), date(2024, 1, 2))


def test_constructor_param_does_not_shadow_config_module():
    # Regression: the constructor parameter used to be named `config`,
    # shadowing the imported `config` module inside __init__.
    client = NbpClient(client_config=NbpClientConfig(table="b"))
    assert client.config.table == "b"
    assert config.MAX_RANGE_DAYS == 93
