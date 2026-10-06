"""Constants and API payloads shared by the tests."""

import re
from typing import Any

from homeassistant.config_entries import ConfigSubentryDataWithId
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.berlin_transport.const import (
    CONF_API_ENDPOINT,
    CONF_API_MAX_RESULTS,
    CONF_DEPARTURES_DIRECTION,
    CONF_DEPARTURES_EXCLUDED_LINES,
    CONF_DEPARTURES_EXCLUDED_STOPS,
    CONF_DEPARTURES_NAME,
    CONF_DEPARTURES_STOP_ID,
    CONF_DEPARTURES_WALKING_TIME,
    CONF_FALLBACK_TIME,
    CONF_SHOW_API_LINE_COLORS,
    CONF_STOP_NAMES,
    CONF_TYPE_BUS,
    CONF_TYPE_EXPRESS,
    CONF_TYPE_FERRY,
    CONF_TYPE_REGIONAL,
    CONF_TYPE_SUBURBAN,
    CONF_TYPE_SUBWAY,
    CONF_TYPE_TRAM,
    CONFIG_ENTRY_VERSION,
    DEFAULT_API_ENDPOINT,
    DOMAIN,
    SUBENTRY_TYPE_STOP,
)

ENDPOINT = DEFAULT_API_ENDPOINT
OTHER_ENDPOINT = "http://vbb-rest.local:3000"

STOP_ID = "900110001"
STOP_NAME = "S+U Schönhauser Allee"
SUBENTRY_ID = "stop_schoenhauser_allee"

# Time all departures in the tests are relative to. Like the API, the tests
# give times in Berlin, which Home Assistant is set to, see `conftest.py`.
NOW = "2026-10-06T12:00:00+02:00"

# A stop as the subentry flow stores it.
STOP_DATA: dict[str, Any] = {
    CONF_DEPARTURES_NAME: STOP_NAME,
    CONF_DEPARTURES_STOP_ID: STOP_ID,
    CONF_DEPARTURES_DIRECTION: [],
    CONF_DEPARTURES_EXCLUDED_STOPS: [],
    CONF_DEPARTURES_EXCLUDED_LINES: [],
    CONF_STOP_NAMES: {},
    CONF_DEPARTURES_WALKING_TIME: 1,
    CONF_SHOW_API_LINE_COLORS: False,
    CONF_TYPE_SUBURBAN: True,
    CONF_TYPE_SUBWAY: True,
    CONF_TYPE_TRAM: True,
    CONF_TYPE_BUS: True,
    CONF_TYPE_FERRY: True,
    CONF_TYPE_EXPRESS: True,
    CONF_TYPE_REGIONAL: True,
}

HUB_OPTIONS: dict[str, Any] = {
    CONF_API_ENDPOINT: ENDPOINT,
    CONF_API_MAX_RESULTS: 15,
    CONF_FALLBACK_TIME: 15,
}


def hub_entry(
    stops: dict[str, dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    title: str = ENDPOINT,
) -> MockConfigEntry:
    """A hub entry with a stop subentry per item of `stops`, keyed by its id.

    Without `stops` the hub has the single stop of `STOP_DATA`.
    """
    if stops is None:
        stops = {SUBENTRY_ID: STOP_DATA}
    subentries = [
        ConfigSubentryDataWithId(
            data=data,
            subentry_id=subentry_id,
            subentry_type=SUBENTRY_TYPE_STOP,
            title=f"{data[CONF_DEPARTURES_NAME]} [{data[CONF_DEPARTURES_STOP_ID]}]",
            unique_id=None,
        )
        for subentry_id, data in stops.items()
    ]
    return MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_ENTRY_VERSION,
        title=title,
        options=HUB_OPTIONS if options is None else options,
        subentries_data=subentries,
    )


def location(stop_id: str, name: str, kind: str = "stop") -> dict[str, Any]:
    """A result of the `/locations` stop search."""
    return {"type": kind, "id": stop_id, "name": name}


def departure(
    line_name: str = "U2",
    when: str | None = "2026-10-06T12:05:00+02:00",
    product: str = "subway",
    **fields: Any,
) -> dict[str, Any]:
    """A departure as returned by `/stops/:id/departures`.

    `fields` set or override the fields of the departure by their API name,
    e.g. `delay` or `stop`.
    """
    return {
        "tripId": f"1|{line_name}|{when}",
        "stop": location(STOP_ID, STOP_NAME),
        "when": when,
        "plannedWhen": when,
        "delay": None,
        "platform": None,
        "plannedPlatform": None,
        "direction": "S+U Pankow",
        "line": {
            "type": "line",
            "id": line_name.lower(),
            "name": line_name,
            "product": product,
        },
        "remarks": [],
        **fields,
    }


def mock_departures(
    aioclient_mock: AiohttpClientMocker,
    departures: list[dict[str, Any]],
    stop_id: str = STOP_ID,
    endpoint: str = ENDPOINT,
) -> None:
    """Answer departure requests for `stop_id` with `departures`."""
    aioclient_mock.get(
        f"{endpoint}/stops/{stop_id}/departures",
        json={"departures": departures},
    )


def mock_any_departures(aioclient_mock: AiohttpClientMocker) -> None:
    """Answer departure requests for any stop with no departures."""
    aioclient_mock.get(re.compile(r"/stops/\w+/departures"), json={"departures": []})


def mock_locations(
    aioclient_mock: AiohttpClientMocker,
    locations: list[dict[str, Any]],
    endpoint: str = ENDPOINT,
) -> None:
    """Answer every stop search with `locations`."""
    aioclient_mock.get(f"{endpoint}/locations", json=locations)


def mock_stop(
    aioclient_mock: AiohttpClientMocker,
    stop_id: str,
    name: str,
    lines: list[str] | None = None,
    endpoint: str = ENDPOINT,
) -> None:
    """Answer requests for a single stop, with the names of its lines."""
    aioclient_mock.get(
        f"{endpoint}/stops/{stop_id}",
        json={
            "type": "stop",
            "id": stop_id,
            "name": name,
            "lines": [{"type": "line", "name": line} for line in lines or []],
        },
    )
