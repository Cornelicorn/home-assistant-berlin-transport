"""Tests for setting up hubs and migrating older config entries."""

from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.berlin_transport.const import (
    CONF_API_ENDPOINT,
    CONF_DEPARTURES_DIRECTION,
    CONF_DEPARTURES_EXCLUDED_LINES,
    CONF_DEPARTURES_EXCLUDED_STOPS,
    CONF_DEPARTURES_NAME,
    CONF_DEPARTURES_STOP_ID,
    CONF_FALLBACK_TIME,
    CONF_UNIQUE_ID,
    CONFIG_ENTRY_VERSION,
    DEFAULT_API_ENDPOINT,
    DOMAIN,
    SUBENTRY_TYPE_STOP,
)

from .common import (
    HUB_OPTIONS,
    OTHER_ENDPOINT,
    STOP_DATA,
    STOP_ID,
    STOP_NAME,
    SUBENTRY_ID,
    hub_entry,
    mock_any_departures,
)

# A stop as version 1 stored it: a config entry of its own, which also held the
# settings now shared by the stops of a hub.
V1_STOP: dict[str, Any] = {
    CONF_DEPARTURES_NAME: STOP_NAME,
    CONF_DEPARTURES_STOP_ID: STOP_ID,
    CONF_DEPARTURES_DIRECTION: "900110002,900007102",
    CONF_DEPARTURES_EXCLUDED_LINES: "S41",
    CONF_API_ENDPOINT: OTHER_ENDPOINT,
    CONF_FALLBACK_TIME: 5,
}


def v1_entry(hass: HomeAssistant, data: dict[str, Any], title: str) -> MockConfigEntry:
    """A version 1 entry with the sensor of its stop."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=data, title=title)
    entry.add_to_hass(hass)
    # The sensor of a stop was identified by the id of its entry.
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        entry.entry_id,
        config_entry=entry,
        suggested_object_id=title,
    )
    return entry


def stops_of(entry: MockConfigEntry) -> dict[str, ConfigSubentry]:
    """The stops of a hub, keyed by the unique id of their sensor."""
    return {
        subentry.data[CONF_UNIQUE_ID]: subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_STOP
    }


async def test_setup_and_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_any_departures(aioclient_mock)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_loaded_entries(DOMAIN) == [config_entry]
    assert len(hass.states.async_entity_ids("sensor")) == 1

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_hub_uses_its_endpoint(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_any_departures(aioclient_mock)
    entry = hub_entry(options={**HUB_OPTIONS, CONF_API_ENDPOINT: OTHER_ENDPOINT})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    [(_, url, _, _)] = aioclient_mock.mock_calls
    assert str(url).startswith(f"{OTHER_ENDPOINT}/stops/{STOP_ID}/departures")


async def test_hub_reloads_when_changed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_any_departures(aioclient_mock)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids("sensor")) == 1

    # A new stop gets its sensor right away.
    hass.config_entries.async_add_subentry(
        config_entry,
        ConfigSubentry(
            data=MappingProxyType(
                {**STOP_DATA, CONF_DEPARTURES_STOP_ID: "900000110501"}
            ),
            subentry_type=SUBENTRY_TYPE_STOP,
            title="Stargarder Str. [900000110501]",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert len(hass.states.async_entity_ids("sensor")) == 2


async def test_migrate_v1_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_any_departures(aioclient_mock)
    entry = v1_entry(hass, V1_STOP, STOP_NAME)
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, entry.entry_id)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The entry became a hub, with the shared settings of the stop.
    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == CONFIG_ENTRY_VERSION
    assert entry.title == OTHER_ENDPOINT
    assert entry.data == {}
    assert entry.options == {CONF_API_ENDPOINT: OTHER_ENDPOINT, CONF_FALLBACK_TIME: 5}
    # Its stop is a subentry now, with lists in place of comma-separated strings.
    stop = stops_of(entry)[entry.entry_id]
    assert stop.title == STOP_NAME
    assert stop.data == {
        CONF_DEPARTURES_NAME: STOP_NAME,
        CONF_DEPARTURES_STOP_ID: STOP_ID,
        CONF_DEPARTURES_DIRECTION: ["900110002", "900007102"],
        CONF_DEPARTURES_EXCLUDED_LINES: ["S41"],
        CONF_UNIQUE_ID: entry.entry_id,
    }
    # The sensor kept its entity id and moved to the stop.
    entity = er.async_get(hass).async_get(entity_id or "")
    assert entity is not None
    assert entity.config_entry_id == entry.entry_id
    assert entity.config_subentry_id == stop.subentry_id
    assert hass.states.get(entity.entity_id) is not None


async def test_migrate_v1_entries_into_one_hub(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_any_departures(aioclient_mock)
    first = v1_entry(hass, V1_STOP, STOP_NAME)
    second = v1_entry(
        hass,
        {
            CONF_DEPARTURES_NAME: "Stargarder Str.",
            CONF_DEPARTURES_STOP_ID: "900000110501",
            CONF_DEPARTURES_EXCLUDED_STOPS: "900110502",
            # The settings of the second entry are dropped for the hub's.
            CONF_FALLBACK_TIME: 30,
        },
        "Stargarder Str.",
    )
    registry = er.async_get(hass)
    second_entity_id = registry.async_get_entity_id("sensor", DOMAIN, second.entry_id)

    # As on the start of Home Assistant, which sets up all entries.
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    # The first entry became the hub of both stops.
    assert hass.config_entries.async_entries(DOMAIN) == [first]
    assert first.state is ConfigEntryState.LOADED
    assert first.options == {CONF_API_ENDPOINT: OTHER_ENDPOINT, CONF_FALLBACK_TIME: 5}
    stops = stops_of(first)
    assert set(stops) == {first.entry_id, second.entry_id}
    assert stops[second.entry_id].data == {
        CONF_DEPARTURES_NAME: "Stargarder Str.",
        CONF_DEPARTURES_STOP_ID: "900000110501",
        CONF_DEPARTURES_EXCLUDED_STOPS: ["900110502"],
        CONF_UNIQUE_ID: second.entry_id,
    }
    # The sensor of the second stop kept its entity id and moved to the hub.
    entity = registry.async_get(second_entity_id or "")
    assert entity is not None
    assert entity.config_entry_id == first.entry_id
    assert entity.config_subentry_id == stops[second.entry_id].subentry_id
    assert len(hass.states.async_entity_ids("sensor")) == 2


async def test_migrate_v1_entry_without_endpoint(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_any_departures(aioclient_mock)
    entry = v1_entry(
        hass,
        {CONF_DEPARTURES_NAME: STOP_NAME, CONF_DEPARTURES_STOP_ID: STOP_ID},
        STOP_NAME,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.title == DEFAULT_API_ENDPOINT
    assert entry.options == {}


async def test_migrate_v2_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_any_departures(aioclient_mock)
    entry = hub_entry(
        {
            SUBENTRY_ID: {
                **STOP_DATA,
                CONF_DEPARTURES_DIRECTION: "900110002,900007102",
                CONF_DEPARTURES_EXCLUDED_STOPS: "900110502",
                CONF_DEPARTURES_EXCLUDED_LINES: "S41",
            }
        }
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, version=2)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == CONFIG_ENTRY_VERSION
    stop = entry.subentries[SUBENTRY_ID]
    assert stop.data[CONF_DEPARTURES_DIRECTION] == ["900110002", "900007102"]
    assert stop.data[CONF_DEPARTURES_EXCLUDED_STOPS] == ["900110502"]
    assert stop.data[CONF_DEPARTURES_EXCLUDED_LINES] == ["S41"]


async def test_downgrade_is_not_supported(hass: HomeAssistant) -> None:
    entry = hub_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, version=CONFIG_ENTRY_VERSION + 1)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
