"""Fixtures shared by the tests."""

import time
from collections.abc import Generator

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import hub_entry


@pytest.fixture(autouse=True, scope="session")
def process_time_zone() -> Generator[None]:
    """Run Python in another time zone than Home Assistant.

    Departures have to be shown in the time zone set in Home Assistant, not in
    the one of the Python process, which is UTC in many containers. With the
    process in yet another time zone, the tests fail if it is used anyway.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("TZ", "America/New_York")
        time.tzset()
        yield
    time.tzset()


@pytest.fixture(autouse=True)
async def berlin_time_zone(hass: HomeAssistant) -> None:
    """Set Home Assistant to the time zone of Berlin, as its users do."""
    await hass.config.async_set_time_zone("Europe/Berlin")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,  # pylint: disable=unused-argument
) -> None:
    """Load the integration from `custom_components` in every test."""


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A hub with a single stop, added to Home Assistant but not set up."""
    entry = hub_entry()
    entry.add_to_hass(hass)
    return entry
