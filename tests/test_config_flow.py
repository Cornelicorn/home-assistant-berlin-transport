"""Tests for adding and editing hubs and their stops."""

import copy
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

import pytest
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.berlin_transport.config_flow import (
    CONF_ALLOW_SHARED_ENDPOINT,
    CONF_CHECK_REACHABLE,
    CONF_ENDPOINT_CHECKS,
    CONF_SEARCH,
    CONF_SELECTED_STOPS,
)
from custom_components.berlin_transport.const import (
    CONF_API_ENDPOINT,
    CONF_API_MAX_RESULTS,
    CONF_DEPARTURES_DIRECTION,
    CONF_DEPARTURES_DURATION,
    CONF_DEPARTURES_EXCLUDED_LINES,
    CONF_DEPARTURES_EXCLUDED_STOPS,
    CONF_DEPARTURES_NAME,
    CONF_DEPARTURES_STOP_ID,
    CONF_DEPARTURES_WALKING_TIME,
    CONF_FALLBACK_TIME,
    CONF_SELECTED_STOP,
    CONF_SHOW_API_LINE_COLORS,
    CONF_STOP_NAMES,
    CONF_UNIQUE_ID,
    DOMAIN,
    SUBENTRY_TYPE_STOP,
)

from .common import (
    ENDPOINT,
    HUB_OPTIONS,
    OTHER_ENDPOINT,
    STOP_DATA,
    STOP_ID,
    STOP_NAME,
    SUBENTRY_ID,
    hub_entry,
    location,
    mock_locations,
    mock_stop,
)

PANKOW = location("900130002", "S+U Pankow")
ALEXANDERPLATZ = location("900100003", "S+U Alexanderplatz")
NEARBY_STOP = location("900110501", "S Schönhauser Allee")
SEARCH_RESULTS = [
    location(STOP_ID, STOP_NAME),
    location("900000123", "Schönhauser Allee 1", kind="location"),
    NEARBY_STOP,
]
STOP_LABEL = f"{STOP_NAME} [{STOP_ID}]"


def mock_search(
    aioclient_mock: AiohttpClientMocker,
    query: str,
    locations: list[dict[str, Any]],
) -> None:
    """Answer the stop search for `query` with `locations`."""
    aioclient_mock.get(f"{ENDPOINT}/locations", params={"query": query}, json=locations)


def select_options(result: Mapping[str, Any], key: str) -> list[Any]:
    """The options of the select field `key` of a form."""
    schema = result["data_schema"]
    assert schema is not None
    field = next(field for field in schema.schema if field == key)
    options: list[Any] = schema.schema[field].config["options"]
    return options


def suggested_value(result: Mapping[str, Any], key: str) -> Any:
    """The value a form suggests for the field `key`."""
    schema = result["data_schema"]
    assert schema is not None
    field = next(field for field in schema.schema if field == key)
    return (field.description or {}).get("suggested_value")


# The hub


async def test_create_hub(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_locations(aioclient_mock, [location(STOP_ID, STOP_NAME)], OTHER_ENDPOINT)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_ENDPOINT: f" {OTHER_ENDPOINT}/ ",
            CONF_API_MAX_RESULTS: 10,
            CONF_FALLBACK_TIME: 0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == OTHER_ENDPOINT
    assert result["data"] == {}
    # The endpoint checks are not stored.
    assert result["options"] == {
        CONF_API_ENDPOINT: OTHER_ENDPOINT,
        CONF_API_MAX_RESULTS: 10,
        CONF_FALLBACK_TIME: 0,
    }
    # The endpoint was checked with a stop search.
    [(_, url, _, _)] = aioclient_mock.mock_calls
    assert url.path == "/locations"
    assert url.query == {"query": "Berlin", "results": "1"}


@pytest.mark.parametrize(
    "existing_options",
    [
        HUB_OPTIONS,
        # Hubs created before the endpoint was stored use the default one.
        {},
    ],
)
async def test_create_hub_for_endpoint_in_use(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    existing_options: dict[str, Any],
) -> None:
    hub_entry(options=existing_options).add_to_hass(hass)
    mock_locations(aioclient_mock, [location(STOP_ID, STOP_NAME)])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_ENDPOINT: f"{ENDPOINT}/"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_ENDPOINT: "endpoint_in_use"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_ENDPOINT: ENDPOINT,
            CONF_ENDPOINT_CHECKS: {
                CONF_CHECK_REACHABLE: True,
                CONF_ALLOW_SHARED_ENDPOINT: True,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


@pytest.mark.parametrize(
    "response",
    [
        {"status": HTTPStatus.SERVICE_UNAVAILABLE},
        # Answers, but is not a vbb-rest API.
        {"json": {"message": "Not Found"}},
    ],
)
async def test_create_hub_for_unreachable_endpoint(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
) -> None:
    aioclient_mock.get(f"{OTHER_ENDPOINT}/locations", **response)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_ENDPOINT: OTHER_ENDPOINT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_ENDPOINT: OTHER_ENDPOINT,
            CONF_ENDPOINT_CHECKS: {
                CONF_CHECK_REACHABLE: False,
                CONF_ALLOW_SHARED_ENDPOINT: False,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_API_ENDPOINT] == OTHER_ENDPOINT
    assert aioclient_mock.call_count == 0


# The options of a hub


async def test_change_endpoint(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_locations(aioclient_mock, [location(STOP_ID, STOP_NAME)], OTHER_ENDPOINT)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**HUB_OPTIONS, CONF_API_ENDPOINT: f"{OTHER_ENDPOINT}/"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {**HUB_OPTIONS, CONF_API_ENDPOINT: OTHER_ENDPOINT}
    # The hub was titled after its endpoint, so it follows it.
    assert config_entry.title == OTHER_ENDPOINT
    assert aioclient_mock.call_count == 1


async def test_change_endpoint_of_renamed_hub(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = hub_entry(title="VBB")
    entry.add_to_hass(hass)
    mock_locations(aioclient_mock, [location(STOP_ID, STOP_NAME)], OTHER_ENDPOINT)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**HUB_OPTIONS, CONF_API_ENDPOINT: OTHER_ENDPOINT}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_API_ENDPOINT] == OTHER_ENDPOINT
    assert entry.title == "VBB"


async def test_change_options_while_api_is_down(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    # An unchanged endpoint is not checked.
    aioclient_mock.get(f"{ENDPOINT}/locations", status=HTTPStatus.BAD_GATEWAY)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**HUB_OPTIONS, CONF_FALLBACK_TIME: 30}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_FALLBACK_TIME] == 30
    assert config_entry.title == ENDPOINT
    assert aioclient_mock.call_count == 0


async def test_change_to_endpoint_in_use(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    other_hub = hub_entry(
        options={**HUB_OPTIONS, CONF_API_ENDPOINT: OTHER_ENDPOINT},
        title=OTHER_ENDPOINT,
    )
    other_hub.add_to_hass(hass)
    mock_locations(aioclient_mock, [location(STOP_ID, STOP_NAME)], OTHER_ENDPOINT)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**HUB_OPTIONS, CONF_API_ENDPOINT: OTHER_ENDPOINT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_API_ENDPOINT: "endpoint_in_use"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **HUB_OPTIONS,
            CONF_API_ENDPOINT: OTHER_ENDPOINT,
            CONF_ENDPOINT_CHECKS: {
                CONF_CHECK_REACHABLE: True,
                CONF_ALLOW_SHARED_ENDPOINT: True,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_API_ENDPOINT] == OTHER_ENDPOINT


async def test_change_to_unreachable_endpoint(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(f"{OTHER_ENDPOINT}/locations", status=HTTPStatus.NOT_FOUND)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**HUB_OPTIONS, CONF_API_ENDPOINT: OTHER_ENDPOINT}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert config_entry.options == HUB_OPTIONS


# Adding a stop


async def start_stop_flow(
    hass: HomeAssistant, entry: MockConfigEntry
) -> SubentryFlowResult:
    """Start adding a stop to `entry`."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_STOP), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_add_stop(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_search(aioclient_mock, "Schönhauser", SEARCH_RESULTS)
    mock_search(aioclient_mock, "Pankow", [PANKOW, ALEXANDERPLATZ])
    mock_stop(aioclient_mock, NEARBY_STOP["id"], NEARBY_STOP["name"])
    mock_stop(aioclient_mock, STOP_ID, STOP_NAME, ["U2", "S41", "S42", "U2"])
    result = await start_stop_flow(hass, config_entry)
    subentries = hass.config_entries.subentries

    # Search the stop and pick it from the stops found.
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SEARCH: "Schönhauser"}
    )
    assert result["step_id"] == "stop"
    assert select_options(result, CONF_SELECTED_STOP) == [
        STOP_LABEL,
        "S Schönhauser Allee [900110501]",
    ]
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SELECTED_STOP: STOP_LABEL}
    )

    # Search direction stops, add two of them and remove one again.
    assert result["step_id"] == CONF_DEPARTURES_DIRECTION
    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_DIRECTION: [], CONF_SEARCH: "Pankow"}
    )
    assert result["step_id"] == "direction_results"
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SELECTED_STOPS: [PANKOW["id"], ALEXANDERPLATZ["id"]]}
    )
    assert result["step_id"] == CONF_DEPARTURES_DIRECTION
    assert select_options(result, CONF_DEPARTURES_DIRECTION) == [
        {"value": PANKOW["id"], "label": "S+U Pankow [900130002]"},
        {"value": ALEXANDERPLATZ["id"], "label": "S+U Alexanderplatz [900100003]"},
    ]
    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_DIRECTION: [PANKOW["id"]]}
    )

    # Type in the id of a stop to ignore, which is shown with its name.
    assert result["step_id"] == CONF_DEPARTURES_EXCLUDED_STOPS
    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_EXCLUDED_STOPS: [NEARBY_STOP["id"]]}
    )
    assert result["step_id"] == CONF_DEPARTURES_EXCLUDED_STOPS
    assert select_options(result, CONF_DEPARTURES_EXCLUDED_STOPS) == [
        {"value": NEARBY_STOP["id"], "label": "S Schönhauser Allee [900110501]"},
    ]
    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_EXCLUDED_STOPS: [NEARBY_STOP["id"]]}
    )

    # The lines of the stop are offered to be ignored.
    assert result["step_id"] == "details"
    assert select_options(result, CONF_DEPARTURES_EXCLUDED_LINES) == [
        "U2",
        "S41",
        "S42",
    ]
    result = await subentries.async_configure(
        result["flow_id"],
        {CONF_DEPARTURES_EXCLUDED_LINES: ["S41"], CONF_DEPARTURES_WALKING_TIME: 0},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == STOP_LABEL
    expected = {
        **STOP_DATA,
        CONF_DEPARTURES_DIRECTION: [PANKOW["id"]],
        CONF_DEPARTURES_EXCLUDED_STOPS: [NEARBY_STOP["id"]],
        CONF_DEPARTURES_EXCLUDED_LINES: ["S41"],
        CONF_DEPARTURES_WALKING_TIME: 0,
        # Only the names of the stops that were kept are stored.
        CONF_STOP_NAMES: {
            PANKOW["id"]: PANKOW["name"],
            NEARBY_STOP["id"]: NEARBY_STOP["name"],
        },
    }
    assert result["data"] == expected
    [subentry] = [
        subentry
        for subentry in config_entry.subentries.values()
        if subentry.subentry_id != SUBENTRY_ID
    ]
    assert subentry.subentry_type == SUBENTRY_TYPE_STOP
    assert subentry.title == STOP_LABEL
    assert subentry.data == expected


async def test_add_stop_without_filters(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_search(aioclient_mock, "Schönhauser", SEARCH_RESULTS)
    # The lines are only offered if the API answers.
    aioclient_mock.get(f"{ENDPOINT}/stops/{STOP_ID}", status=HTTPStatus.BAD_GATEWAY)
    result = await start_stop_flow(hass, config_entry)
    subentries = hass.config_entries.subentries

    result = await subentries.async_configure(
        result["flow_id"], {CONF_SEARCH: "Schönhauser"}
    )
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SELECTED_STOP: STOP_LABEL}
    )
    result = await subentries.async_configure(result["flow_id"], {})
    assert result["step_id"] == CONF_DEPARTURES_EXCLUDED_STOPS
    result = await subentries.async_configure(result["flow_id"], {})
    assert result["step_id"] == "details"
    assert select_options(result, CONF_DEPARTURES_EXCLUDED_LINES) == []
    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_DURATION: 30}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**STOP_DATA, CONF_DEPARTURES_DURATION: 30}


@pytest.mark.parametrize(
    ("response", "errors"),
    [
        # Addresses and points of interest are no stops.
        ({"json": [SEARCH_RESULTS[1]]}, {CONF_SEARCH: "no_stops_found"}),
        ({"json": []}, {CONF_SEARCH: "no_stops_found"}),
        ({"status": HTTPStatus.SERVICE_UNAVAILABLE}, {"base": "cannot_connect"}),
    ],
)
async def test_search_stop_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
    errors: dict[str, str],
) -> None:
    aioclient_mock.get(f"{ENDPOINT}/locations", **response)
    result = await start_stop_flow(hass, config_entry)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_SEARCH: "Schönhauser"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == errors


async def test_search_direction_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_search(aioclient_mock, "Schönhauser", SEARCH_RESULTS)
    mock_search(aioclient_mock, "Nowhere", [])
    aioclient_mock.get(f"{ENDPOINT}/locations", status=HTTPStatus.BAD_GATEWAY)
    subentries = hass.config_entries.subentries
    result = await start_stop_flow(hass, config_entry)
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SEARCH: "Schönhauser"}
    )
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SELECTED_STOP: STOP_LABEL}
    )

    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_DIRECTION: [], CONF_SEARCH: "Nowhere"}
    )
    assert result["step_id"] == CONF_DEPARTURES_DIRECTION
    assert result["errors"] == {CONF_SEARCH: "no_stops_found"}
    # The search is kept, so it can be corrected.
    assert suggested_value(result, CONF_SEARCH) == "Nowhere"

    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_DIRECTION: [], CONF_SEARCH: "Pankow"}
    )
    assert result["step_id"] == CONF_DEPARTURES_DIRECTION
    assert result["errors"] == {"base": "cannot_connect"}


# Reconfiguring a stop


async def test_reconfigure_stop(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    stored = {
        **STOP_DATA,
        CONF_UNIQUE_ID: "entity_of_old_entry",
        CONF_DEPARTURES_DIRECTION: [PANKOW["id"]],
        CONF_STOP_NAMES: {PANKOW["id"]: PANKOW["name"]},
        CONF_DEPARTURES_EXCLUDED_LINES: ["S41", "N2"],
        CONF_DEPARTURES_DURATION: 30,
    }
    entry = hub_entry({SUBENTRY_ID: copy.deepcopy(stored)})
    entry.add_to_hass(hass)
    mock_search(aioclient_mock, "Alexanderplatz", [ALEXANDERPLATZ])
    mock_search(aioclient_mock, "Schönhauser", SEARCH_RESULTS)
    mock_stop(aioclient_mock, STOP_ID, STOP_NAME, ["U2", "S41"])
    subentries = hass.config_entries.subentries

    # Reconfiguring starts with the direction filter of the stop.
    result = await subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_STOP),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": SUBENTRY_ID},
    )
    assert result["step_id"] == CONF_DEPARTURES_DIRECTION
    assert suggested_value(result, CONF_DEPARTURES_DIRECTION) == [PANKOW["id"]]
    assert select_options(result, CONF_DEPARTURES_DIRECTION) == [
        {"value": PANKOW["id"], "label": "S+U Pankow [900130002]"},
    ]

    result = await subentries.async_configure(
        result["flow_id"],
        {CONF_DEPARTURES_DIRECTION: [PANKOW["id"]], CONF_SEARCH: "Alexanderplatz"},
    )
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SELECTED_STOPS: [ALEXANDERPLATZ["id"]]}
    )
    # Nothing is stored until the flow is done.
    assert entry.subentries[SUBENTRY_ID].data == stored

    result = await subentries.async_configure(
        result["flow_id"],
        {CONF_DEPARTURES_DIRECTION: [PANKOW["id"], ALEXANDERPLATZ["id"]]},
    )

    # Ignored stops are searched the same way.
    assert result["step_id"] == CONF_DEPARTURES_EXCLUDED_STOPS
    result = await subentries.async_configure(
        result["flow_id"],
        {CONF_DEPARTURES_EXCLUDED_STOPS: [], CONF_SEARCH: "Schönhauser"},
    )
    assert result["step_id"] == "excluded_stops_results"
    assert select_options(result, CONF_SELECTED_STOPS) == [
        {"value": STOP_ID, "label": STOP_LABEL},
        {"value": NEARBY_STOP["id"], "label": "S Schönhauser Allee [900110501]"},
    ]
    result = await subentries.async_configure(
        result["flow_id"], {CONF_SELECTED_STOPS: [NEARBY_STOP["id"]]}
    )
    assert result["step_id"] == CONF_DEPARTURES_EXCLUDED_STOPS
    result = await subentries.async_configure(
        result["flow_id"], {CONF_DEPARTURES_EXCLUDED_STOPS: [NEARBY_STOP["id"]]}
    )

    # Ignored lines stay on offer, even if the API does not list them.
    assert result["step_id"] == "details"
    assert select_options(result, CONF_DEPARTURES_EXCLUDED_LINES) == [
        "U2",
        "S41",
        "N2",
    ]
    assert suggested_value(result, CONF_DEPARTURES_DURATION) == 30

    # Clearing the duration leaves it out of the input.
    result = await subentries.async_configure(
        result["flow_id"],
        {CONF_DEPARTURES_EXCLUDED_LINES: ["S41"], CONF_SHOW_API_LINE_COLORS: True},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    expected = {**stored}
    del expected[CONF_DEPARTURES_DURATION]
    expected.update(
        {
            CONF_DEPARTURES_DIRECTION: [PANKOW["id"], ALEXANDERPLATZ["id"]],
            CONF_DEPARTURES_EXCLUDED_STOPS: [NEARBY_STOP["id"]],
            CONF_STOP_NAMES: {
                PANKOW["id"]: PANKOW["name"],
                ALEXANDERPLATZ["id"]: ALEXANDERPLATZ["name"],
                NEARBY_STOP["id"]: NEARBY_STOP["name"],
            },
            CONF_DEPARTURES_EXCLUDED_LINES: ["S41"],
            CONF_SHOW_API_LINE_COLORS: True,
        }
    )
    subentry = entry.subentries[SUBENTRY_ID]
    assert subentry.data == expected
    # The stop itself cannot be changed.
    assert subentry.data[CONF_DEPARTURES_STOP_ID] == STOP_ID
    assert subentry.data[CONF_DEPARTURES_NAME] == STOP_NAME
    assert subentry.title == STOP_LABEL


async def test_reconfigure_stop_of_older_version(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    # Stops saved before the names of direction stops were stored.
    stored = {**STOP_DATA, CONF_DEPARTURES_DIRECTION: [PANKOW["id"]]}
    del stored[CONF_STOP_NAMES]
    entry = hub_entry({SUBENTRY_ID: stored})
    entry.add_to_hass(hass)
    mock_stop(aioclient_mock, PANKOW["id"], PANKOW["name"])

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_STOP),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": SUBENTRY_ID},
    )

    # The names are looked up.
    assert select_options(result, CONF_DEPARTURES_DIRECTION) == [
        {"value": PANKOW["id"], "label": "S+U Pankow [900130002]"},
    ]
