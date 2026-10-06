"""Tests for the departures sensor of a stop."""

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import ATTR_FRIENDLY_NAME, ATTR_ICON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.berlin_transport.const import (
    CONF_API_MAX_RESULTS,
    CONF_DEPARTURES_DIRECTION,
    CONF_DEPARTURES_DURATION,
    CONF_DEPARTURES_EXCLUDED_LINES,
    CONF_DEPARTURES_EXCLUDED_STOPS,
    CONF_DEPARTURES_WALKING_TIME,
    CONF_FALLBACK_TIME,
    CONF_SHOW_API_LINE_COLORS,
    CONF_TYPE_BUS,
    DEFAULT_ICON,
    DOMAIN,
    ISSUE_YAML_CSV_LISTS,
)
from custom_components.berlin_transport.sensor import SCAN_INTERVAL

from .common import (
    ENDPOINT,
    HUB_OPTIONS,
    NOW,
    STOP_DATA,
    STOP_ID,
    STOP_NAME,
    SUBENTRY_ID,
    departure,
    hub_entry,
    location,
    mock_departures,
)

pytestmark = pytest.mark.freeze_time(NOW)

DEPARTURES_URL = f"{ENDPOINT}/stops/{STOP_ID}/departures"
NEARBY_STOP = location("900110501", "S Schönhauser Allee")
YAML_ENTITY_ID = "sensor.s_u_schonhauser_allee"


async def setup_hub(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Set up a hub and return the entity id of the departures of its stop."""
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, SUBENTRY_ID)
    assert entity_id is not None
    return entity_id


def stop_hub(**stop: Any) -> MockConfigEntry:
    """A hub with a single stop whose settings differ by `stop`."""
    return hub_entry({SUBENTRY_ID: {**STOP_DATA, **stop}})


def shown_lines(hass: HomeAssistant, entity_id: str) -> list[tuple[str, str]]:
    """The line and time of the departures a sensor shows."""
    state = hass.states.get(entity_id)
    assert state is not None
    return [(d["line_name"], d["time"]) for d in state.attributes["departures"]]


async def update(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    """Let `delta` pass, so the sensors poll the API."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_sensor_of_stop(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_departures(
        aioclient_mock,
        [
            departure("U2", "2026-10-06T12:05:00+02:00"),
            departure("S41", "2026-10-06T12:12:00+02:00", "suburban"),
        ],
    )

    entity_id = await setup_hub(hass, config_entry)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Next U2 at 12:05"
    assert state.attributes[ATTR_ICON] == "mdi:subway"
    assert state.attributes[ATTR_FRIENDLY_NAME] == f"{STOP_NAME} Departures"
    assert shown_lines(hass, entity_id) == [("U2", "12:05"), ("S41", "12:12")]
    assert state.attributes["departures"][1] == {
        "line_name": "S41",
        "line_type": "suburban",
        "time": "12:12",
        "timestamp": datetime.fromisoformat("2026-10-06T12:12:00+02:00"),
        "direction": "S+U Pankow",
        "color": "#008D4F",
        "text_color": None,
        "cancelled": False,
        "delay": None,
        "warnings": None,
        "walking_time": 1,
        "platform": None,
        "planned_platform": None,
        "other_stop_name": None,
    }


async def test_device_of_stop(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_departures(aioclient_mock, [])

    entity_id = await setup_hub(hass, config_entry)

    entity = er.async_get(hass).async_get(entity_id)
    assert entity is not None
    assert entity.config_subentry_id == SUBENTRY_ID
    assert entity.device_id is not None
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device is not None
    assert device.identifiers == {(DOMAIN, SUBENTRY_ID)}
    assert device.name == STOP_NAME
    assert device.entry_type is dr.DeviceEntryType.SERVICE

    # The device belongs to the stop, so it goes when the stop is removed.
    assert hass.config_entries.async_remove_subentry(config_entry, SUBENTRY_ID)
    await hass.async_block_till_done()
    assert dr.async_get(hass).async_get(device.id) is None


async def test_departures_request(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_departures(aioclient_mock, [])
    entry = hub_entry(
        {
            SUBENTRY_ID: {
                **STOP_DATA,
                CONF_DEPARTURES_WALKING_TIME: 5,
                CONF_DEPARTURES_DURATION: 30,
                CONF_TYPE_BUS: False,
            }
        },
        options={**HUB_OPTIONS, CONF_API_MAX_RESULTS: 10},
    )

    await setup_hub(hass, entry)

    [(_, url, _, _)] = aioclient_mock.mock_calls
    assert url.path == f"/stops/{STOP_ID}/departures"
    assert url.query == {
        # Departures that cannot be reached on foot anymore are left out.
        "when": "2026-10-06T12:05:00+02:00",
        "results": "10",
        "duration": "30",
        "suburban": "true",
        "subway": "true",
        "tram": "true",
        "bus": "false",
        "ferry": "true",
        "express": "true",
        "regional": "true",
    }


async def test_walking_time_of_zero(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_departures(aioclient_mock, [])

    await setup_hub(hass, stop_hub(**{CONF_DEPARTURES_WALKING_TIME: 0}))

    assert aioclient_mock.mock_calls[0][1].query["when"] == NOW


async def test_no_departures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_departures(aioclient_mock, [])

    entity_id = await setup_hub(hass, config_entry)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "N/A"
    assert state.attributes[ATTR_ICON] == DEFAULT_ICON
    assert state.attributes["departures"] == []


async def test_response_without_departures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    aioclient_mock.get(DEPARTURES_URL, json={})

    entity_id = await setup_hub(hass, config_entry)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "N/A"
    assert f"No departures found for {STOP_ID}" in caplog.text


async def test_direction_filter(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    ring_north = departure("S41", "2026-10-06T12:03:00+02:00", "suburban")
    aioclient_mock.get(
        DEPARTURES_URL,
        params={"direction": "900110002"},
        json={"departures": [ring_north, departure("U2", "2026-10-06T12:05:00+02:00")]},
    )
    aioclient_mock.get(
        DEPARTURES_URL,
        params={"direction": "900007102"},
        json={
            "departures": [
                departure("S42", "2026-10-06T12:08:00+02:00", "suburban"),
                ring_north,
            ]
        },
    )
    entry = stop_hub(**{CONF_DEPARTURES_DIRECTION: ["900110002", "900007102"]})

    entity_id = await setup_hub(hass, entry)

    # One request per direction, merged in order of time and without the
    # departure both directions returned.
    assert [call[1].query["direction"] for call in aioclient_mock.mock_calls] == [
        "900110002",
        "900007102",
    ]
    assert shown_lines(hass, entity_id) == [
        ("S41", "12:03"),
        ("U2", "12:05"),
        ("S42", "12:08"),
    ]


async def test_direction_filter_fails_with_any_direction(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(
        DEPARTURES_URL,
        params={"direction": "900110002"},
        json={"departures": [departure()]},
    )
    aioclient_mock.get(
        DEPARTURES_URL,
        params={"direction": "900007102"},
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
    )
    entry = stop_hub(**{CONF_DEPARTURES_DIRECTION: ["900110002", "900007102"]})

    entity_id = await setup_hub(hass, entry)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_excluded_stops_and_lines(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_departures(
        aioclient_mock,
        [
            departure("S41", "2026-10-06T12:03:00+02:00", "suburban"),
            departure("U2", "2026-10-06T12:05:00+02:00"),
            departure("M1", "2026-10-06T12:06:00+02:00", "tram", stop=NEARBY_STOP),
            departure("12", "2026-10-06T12:07:00+02:00", "tram"),
        ],
    )
    entry = stop_hub(
        **{
            CONF_DEPARTURES_EXCLUDED_STOPS: [NEARBY_STOP["id"]],
            CONF_DEPARTURES_EXCLUDED_LINES: ["S41"],
        }
    )

    entity_id = await setup_hub(hass, entry)

    assert shown_lines(hass, entity_id) == [("U2", "12:05"), ("12", "12:07")]


async def test_departure_from_nearby_stop(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_departures(
        aioclient_mock,
        [
            departure("U2", "2026-10-06T12:05:00+02:00"),
            departure("M1", "2026-10-06T12:06:00+02:00", "tram", stop=NEARBY_STOP),
        ],
    )

    entity_id = await setup_hub(hass, config_entry)

    state = hass.states.get(entity_id)
    assert state is not None
    assert [d["other_stop_name"] for d in state.attributes["departures"]] == [
        None,
        NEARBY_STOP["name"],
    ]


async def test_official_line_colors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    line = {"name": "U2", "product": "subway", "color": {"fg": "#fff", "bg": "#da421e"}}
    mock_departures(aioclient_mock, [departure(line=line)])

    entity_id = await setup_hub(hass, stop_hub(**{CONF_SHOW_API_LINE_COLORS: True}))

    state = hass.states.get(entity_id)
    assert state is not None
    [shown] = state.attributes["departures"]
    assert (shown["color"], shown["text_color"]) == ("#da421e", "#fff")


async def test_polls_api(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_departures(aioclient_mock, [departure("U2", "2026-10-06T12:05:00+02:00")])
    entity_id = await setup_hub(hass, config_entry)
    assert aioclient_mock.call_count == 1

    aioclient_mock.clear_requests()
    mock_departures(aioclient_mock, [departure("U2", "2026-10-06T12:08:00+02:00")])
    await update(hass, freezer, SCAN_INTERVAL)

    assert aioclient_mock.call_count == 1
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Next U2 at 12:08"


async def test_fallback_while_api_is_down(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_departures(
        aioclient_mock,
        [
            departure("U2", "2026-10-06T12:05:00+02:00"),
            departure("U2", "2026-10-06T12:15:00+02:00"),
            departure("U2", "2026-10-06T12:25:00+02:00"),
        ],
    )
    entity_id = await setup_hub(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEPARTURES_URL, status=HTTPStatus.SERVICE_UNAVAILABLE)

    # Within the fallback time, the departures that have not left yet stay.
    await update(hass, freezer, timedelta(minutes=10))
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Next U2 at 12:15"
    assert shown_lines(hass, entity_id) == [("U2", "12:15"), ("U2", "12:25")]

    # After it, the sensor is unavailable.
    await update(hass, freezer, timedelta(minutes=6))
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    # Until the API answers again.
    aioclient_mock.clear_requests()
    mock_departures(aioclient_mock, [departure("U2", "2026-10-06T12:25:00+02:00")])
    await update(hass, freezer, SCAN_INTERVAL)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Next U2 at 12:25"


async def test_fallback_ends_with_last_departure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_departures(aioclient_mock, [departure("U2", "2026-10-06T12:01:00+02:00")])
    entity_id = await setup_hub(hass, config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEPARTURES_URL, status=HTTPStatus.SERVICE_UNAVAILABLE)

    await update(hass, freezer, SCAN_INTERVAL)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_fallback_turned_off(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_departures(aioclient_mock, [departure("U2", "2026-10-06T12:15:00+02:00")])
    entry = hub_entry(options={**HUB_OPTIONS, CONF_FALLBACK_TIME: 0})
    entity_id = await setup_hub(hass, entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEPARTURES_URL, status=HTTPStatus.SERVICE_UNAVAILABLE)

    await update(hass, freezer, SCAN_INTERVAL)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_yaml_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    mock_departures(aioclient_mock, [departure("U2"), departure("S41")])
    config = {
        "platform": DOMAIN,
        "departures": [
            {
                "name": STOP_NAME,
                "stop_id": int(STOP_ID),
                "excluded_lines": ["S41"],
            }
        ],
    }

    assert await async_setup_component(hass, "sensor", {"sensor": [config]})
    await hass.async_block_till_done()

    state = hass.states.get(YAML_ENTITY_ID)
    assert state is not None
    assert state.state == "Next U2 at 12:05"
    assert state.attributes[ATTR_FRIENDLY_NAME] == STOP_NAME
    assert shown_lines(hass, YAML_ENTITY_ID) == [("U2", "12:05")]
    entity = er.async_get(hass).async_get(YAML_ENTITY_ID)
    assert entity is not None
    assert entity.unique_id == f"stop_{STOP_ID}_{STOP_NAME}_departures"
    assert entity.device_id is None
    assert not issue_registry.issues


async def test_yaml_stop_with_comma_separated_lists(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    mock_departures(aioclient_mock, [departure("U2"), departure("S41")])
    mock_departures(aioclient_mock, [], stop_id="900000110501")
    config = {
        "platform": DOMAIN,
        "departures": [
            {
                "name": STOP_NAME,
                "stop_id": int(STOP_ID),
                "excluded_lines": "S41,S42",
                "direction": "900110002",
            },
            {
                "name": "Stargarder Str.",
                "stop_id": 900000110501,
                "excluded_stops": ["900110502", "900007102"],
            },
        ],
    }

    assert await async_setup_component(hass, "sensor", {"sensor": [config]})
    await hass.async_block_till_done()

    # The comma-separated form still works.
    assert shown_lines(hass, YAML_ENTITY_ID) == [("U2", "12:05")]
    # But a repair issue names the stops and options to change.
    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_YAML_CSV_LISTS)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {
        "stops": STOP_NAME,
        "options": CONF_DEPARTURES_EXCLUDED_LINES,
    }
