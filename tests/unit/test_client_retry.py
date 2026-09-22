import json
from pathlib import Path

import pytest
import requests
import requests_mock

from weatherml.ingestion.client import (
    WeatherstackClient,
    WeatherstackClientError,
    WeatherstackQuotaExceededError,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
BASE_URL = "http://api.weatherstack.com/current"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def client():
    return WeatherstackClient(base_url=BASE_URL, access_key="test-key", timeout_seconds=5)


def test_successful_response_is_parsed(client):
    with requests_mock.Mocker() as m:
        m.get(BASE_URL, json=_load("weatherstack_success.json"))
        result = client.get_current("40.714,-74.006")
    assert result.location.name == "New York"
    assert result.current.temperature == 16


def test_invalid_key_error_is_not_retried(client):
    """error code 101 is a non-retryable client error — retrying a bad key
    just burns time and, on a real account, quota.
    """
    with requests_mock.Mocker() as m:
        m.get(BASE_URL, json=_load("weatherstack_error_invalid_key.json"))
        with pytest.raises(WeatherstackClientError):
            client.get_current("40.714,-74.006")
    assert m.call_count == 1


def test_quota_error_is_retried_then_raised(client):
    """error code 104 is retryable — tenacity retries up to 4 attempts total
    before surfacing WeatherstackQuotaExceededError.
    """
    with requests_mock.Mocker() as m:
        m.get(BASE_URL, json=_load("weatherstack_error_quota.json"))
        with pytest.raises(WeatherstackQuotaExceededError):
            client.get_current("40.714,-74.006")
    assert m.call_count == 4


def test_connection_error_is_retried(client):
    with requests_mock.Mocker() as m:
        m.get(BASE_URL, exc=requests.ConnectionError)
        with pytest.raises(requests.ConnectionError):
            client.get_current("40.714,-74.006")
    assert m.call_count == 4


def test_success_after_transient_failure(client):
    with requests_mock.Mocker() as m:
        m.get(
            BASE_URL,
            [
                {"exc": requests.ConnectionError},
                {"json": _load("weatherstack_success.json")},
            ],
        )
        result = client.get_current("40.714,-74.006")
    assert result.location.name == "New York"
    assert m.call_count == 2
