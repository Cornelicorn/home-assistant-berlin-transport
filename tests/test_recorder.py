"""Tests for what the recorder keeps of the departures sensor."""

from typing import Any

import pytest
from homeassistant.components.recorder.core import Recorder
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .common import departure, mock_departures


@pytest.fixture
def mock_recorder_before_hass(
    async_test_recorder: Any,  # pylint: disable=unused-argument
) -> None:
    """Prepare the database of the recorder before Home Assistant starts."""


async def test_departures_are_not_recorded(
    recorder_mock: Recorder,  # pylint: disable=unused-argument
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    mock_departures(aioclient_mock, [departure()])
    start = dt_util.utcnow()

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    [entity_id] = hass.states.async_entity_ids("sensor")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["departures"]
    history = await hass.async_add_executor_job(
        get_significant_states, hass, start, None, [entity_id]
    )
    [recorded] = history[entity_id]
    assert isinstance(recorded, State)
    assert recorded.state == state.state
    assert "departures" not in recorded.attributes
