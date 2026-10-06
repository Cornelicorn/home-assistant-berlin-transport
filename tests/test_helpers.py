"""Tests for the helpers shared by the integration."""

from typing import Any

import pytest

from custom_components.berlin_transport.const import (
    CONF_DEPARTURES_DIRECTION,
    CONF_DEPARTURES_EXCLUDED_LINES,
    CONF_DEPARTURES_EXCLUDED_STOPS,
    CONF_DEPARTURES_NAME,
)
from custom_components.berlin_transport.helpers import (
    as_string_list,
    is_legacy_csv,
    normalized_list_options,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ("", [""]),
        ("S41", ["S41"]),
        ("S41,S42", ["S41", "S42"]),
        (["S41", "S42"], ["S41", "S42"]),
        (("S41", "S42"), ["S41", "S42"]),
        (900110001, [900110001]),
    ],
)
def test_as_string_list(value: Any, expected: list[Any]) -> None:
    assert as_string_list(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("S41,S42", True),
        ("S41", False),
        (["S41,S42"], False),
        (None, False),
        (900110001, False),
    ],
)
def test_is_legacy_csv(value: Any, expected: bool) -> None:
    assert is_legacy_csv(value) is expected


def test_normalized_list_options() -> None:
    data = {
        CONF_DEPARTURES_NAME: "S+U Schönhauser Allee",
        CONF_DEPARTURES_DIRECTION: "900110002,900007102",
        CONF_DEPARTURES_EXCLUDED_LINES: ["S41"],
    }

    assert normalized_list_options(data) == {
        CONF_DEPARTURES_DIRECTION: ["900110002", "900007102"],
        CONF_DEPARTURES_EXCLUDED_LINES: ["S41"],
    }


def test_normalized_list_options_leaves_out_unset_options() -> None:
    assert normalized_list_options({CONF_DEPARTURES_NAME: "Stop"}) == {}
    assert normalized_list_options({CONF_DEPARTURES_EXCLUDED_STOPS: None}) == {
        CONF_DEPARTURES_EXCLUDED_STOPS: []
    }
