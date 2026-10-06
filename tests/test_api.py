"""Tests for the client of the vbb-rest API."""

import logging
from http import HTTPStatus

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.berlin_transport.api import TransportApi, async_create_api

from .common import ENDPOINT, STOP_ID, departure, location, mock_locations

LOCATIONS = [location(STOP_ID, "S+U Schönhauser Allee")]
LOGGER = "custom_components.berlin_transport.api"


def api_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The records logged by the API client."""
    return [record for record in caplog.records if record.name == LOGGER]


def api_levels(caplog: pytest.LogCaptureFixture) -> list[int]:
    """The levels of the records logged by the API client."""
    return [record.levelno for record in api_records(caplog)]


@pytest.fixture(name="api")
async def api_fixture(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,  # pylint: disable=unused-argument
) -> TransportApi:
    """A client for the default endpoint, whose requests `aioclient_mock` answers."""
    return await async_create_api(hass, ENDPOINT)


async def test_locations(
    api: TransportApi, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_locations(aioclient_mock, LOCATIONS)

    assert await api.locations("Schönhauser", 5) == LOCATIONS

    [(method, url, _, headers)] = aioclient_mock.mock_calls
    assert method == "GET"
    assert url.path == "/locations"
    assert url.query == {"query": "Schönhauser", "results": "5"}
    # Identify the integration to the operators of the API.
    user_agent = headers["User-Agent"]
    assert "home-assistant-berlin-transport/" in user_agent
    assert "https://github.com/vas3k/home-assistant-berlin-transport" in user_agent


async def test_stop(api: TransportApi, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{ENDPOINT}/stops/{STOP_ID}", json=LOCATIONS[0])

    assert await api.stop(STOP_ID, {"linesOfStops": "true"}) == LOCATIONS[0]
    assert aioclient_mock.mock_calls[0][1].query == {"linesOfStops": "true"}


async def test_departures(
    api: TransportApi, aioclient_mock: AiohttpClientMocker
) -> None:
    response = {"departures": [departure()]}
    aioclient_mock.get(f"{ENDPOINT}/stops/{STOP_ID}/departures", json=response)

    assert await api.departures(int(STOP_ID), {"results": 15}) == response


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ({"status": HTTPStatus.SERVICE_UNAVAILABLE}, "503"),
        ({"exc": aiohttp.ClientConnectionError("Connection refused")}, "refused"),
        ({"exc": TimeoutError()}, "no answer within 30 seconds"),
    ],
    ids=["http_error", "connection_error", "timeout"],
)
async def test_failed_request_returns_none(
    api: TransportApi,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    error: dict[str, object],
    reason: str,
) -> None:
    aioclient_mock.get(f"{ENDPOINT}/locations", **error)

    assert await api.locations("Schönhauser", 5) is None
    [record] = api_records(caplog)
    assert record.levelno == logging.WARNING
    assert reason in record.getMessage()


async def test_invalid_response_returns_none(
    api: TransportApi,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    aioclient_mock.get(f"{ENDPOINT}/locations", text="<html>Bad Gateway</html>")

    assert await api.locations("Schönhauser", 5) is None
    assert "Unexpected error for /locations" in caplog.text


async def test_outage_is_logged_once(
    api: TransportApi,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    aioclient_mock.get(f"{ENDPOINT}/locations", status=HTTPStatus.TOO_MANY_REQUESTS)

    for _ in range(3):
        assert await api.locations("Schönhauser", 5) is None

    assert api_levels(caplog) == [logging.WARNING, logging.DEBUG, logging.DEBUG]

    # Once the API works again, that is logged, and the next outage warned of.
    caplog.clear()
    aioclient_mock.clear_requests()
    mock_locations(aioclient_mock, LOCATIONS)
    assert await api.locations("Schönhauser", 5) == LOCATIONS
    assert api_levels(caplog) == [logging.INFO]
    assert "works again" in caplog.text

    caplog.clear()
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{ENDPOINT}/locations", status=HTTPStatus.BAD_GATEWAY)
    assert await api.locations("Schönhauser", 5) is None
    assert api_levels(caplog) == [logging.WARNING]
