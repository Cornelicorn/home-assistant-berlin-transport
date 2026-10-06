"""Tests for turning API departures into the sensor's departures."""

from datetime import datetime

import pytest

from custom_components.berlin_transport.const import DEFAULT_ICON
from custom_components.berlin_transport.departure import Departure

from .common import NOW, STOP_ID, STOP_NAME, departure, location

API_COLORS = {"fg": "#ffffff", "bg": "#da421e"}
# A stop of the same station as `STOP_ID`.
NEARBY_STOP = location("900110501", "S Schönhauser Allee")


def test_from_dict() -> None:
    result = Departure.from_dict(
        departure(
            "U2",
            "2026-10-06T12:06:00+02:00",
            plannedWhen="2026-10-06T12:05:00+02:00",
            delay=60,
            platform="2",
            plannedPlatform="1",
            cancelled=False,
            line={"name": "U2", "product": "subway", "color": API_COLORS},
            currentTripPosition={"latitude": 52.54, "longitude": 13.41},
        )
    )

    assert result == Departure(
        trip_id="1|U2|2026-10-06T12:06:00+02:00",
        line_name="U2",
        line_type="subway",
        timestamp=datetime.fromisoformat("2026-10-06T12:06:00+02:00"),
        icon="mdi:subway",
        direction="S+U Pankow",
        bg_color="#da421e",
        fg_color="#ffffff",
        fallback_color="#2864A6",
        location=(52.54, 13.41),
        cancelled=False,
        delay=60,
        warnings=None,
        platform="2",
        planned_platform="1",
        stop_id=STOP_ID,
        stop_name="S+U Schönhauser Allee",
    )
    assert result.time == "12:06"


@pytest.mark.freeze_time(NOW)
def test_from_dict_tolerates_null_fields() -> None:
    result = Departure.from_dict(
        {
            "tripId": None,
            "stop": None,
            "when": None,
            "plannedWhen": None,
            "delay": None,
            "platform": None,
            "plannedPlatform": None,
            "direction": None,
            "line": None,
            "remarks": None,
            "currentTripPosition": None,
            "cancelled": None,
        }
    )

    assert result.trip_id == "unknown"
    assert result.line_name is None
    assert result.icon == DEFAULT_ICON
    assert result.fallback_color is None
    assert result.timestamp == datetime.fromisoformat(NOW)
    assert result.location is None
    assert result.cancelled is False
    assert result.warnings is None
    assert result.stop_id is None


def test_from_dict_uses_planned_time_without_realtime() -> None:
    # Cancelled departures have no realtime `when`.
    result = Departure.from_dict(
        departure(
            when=None,
            plannedWhen="2026-10-06T12:07:00+02:00",
            cancelled=True,
        )
    )

    assert result.timestamp == datetime.fromisoformat("2026-10-06T12:07:00+02:00")
    assert result.cancelled is True


@pytest.mark.freeze_time(NOW)
def test_from_dict_falls_back_to_now_for_invalid_times() -> None:
    result = Departure.from_dict(departure(when="soon"))

    assert result.timestamp == datetime.fromisoformat(NOW)


def test_from_dict_needs_both_coordinates_for_location() -> None:
    result = Departure.from_dict(departure(currentTripPosition={"latitude": 52.54}))

    assert result.location is None


def test_from_dict_keeps_only_complete_warnings() -> None:
    result = Departure.from_dict(
        departure(
            remarks=[
                {"type": "warning", "id": "1", "summary": "Construction work"},
                {"type": "hint", "id": "2", "summary": "Bicycles allowed"},
                {"type": "warning", "id": "3", "summary": None},
                {"type": "warning", "summary": "No id"},
            ]
        )
    )

    assert result.warnings == [{"id": "1", "summary": "Construction work"}]


@pytest.mark.parametrize(
    ("product", "icon", "color"),
    [
        ("suburban", "mdi:subway-variant", "#008D4F"),
        ("subway", "mdi:subway", "#2864A6"),
        ("tram", "mdi:tram", "#D82020"),
        ("bus", "mdi:bus", "#A5027D"),
        ("ferry", "mdi:ferry", "#0080BA"),
        ("express", "mdi:train", "#4D4D4D"),
        ("regional", "mdi:train", "#F01414"),
        ("cablecar", DEFAULT_ICON, None),
    ],
)
def test_from_dict_visuals_of_product(product: str, icon: str, color: str) -> None:
    result = Departure.from_dict(departure(product=product))

    assert result.icon == icon
    assert result.fallback_color == color


def test_to_dict() -> None:
    result = Departure.from_dict(
        departure(
            delay=120,
            platform="2",
            plannedPlatform="1",
            remarks=[{"type": "warning", "id": "1", "summary": "Construction"}],
        )
    )

    assert result.to_dict(
        show_api_line_colors=False, walking_time=5, stop_id=STOP_ID
    ) == {
        "line_name": "U2",
        "line_type": "subway",
        "time": "12:05",
        "timestamp": datetime.fromisoformat("2026-10-06T12:05:00+02:00"),
        "direction": "S+U Pankow",
        "color": "#2864A6",
        "text_color": None,
        "cancelled": False,
        "delay": 120,
        "warnings": [{"id": "1", "summary": "Construction"}],
        "walking_time": 5,
        "platform": "2",
        "planned_platform": "1",
        "other_stop_name": None,
    }


@pytest.mark.parametrize(
    ("show_api_line_colors", "line_color", "color", "text_color"),
    [
        (False, API_COLORS, "#2864A6", None),
        (True, API_COLORS, "#da421e", "#ffffff"),
        # Not every line has an official color.
        (True, None, "#2864A6", None),
    ],
)
def test_to_dict_colors(
    show_api_line_colors: bool,
    line_color: dict[str, str] | None,
    color: str,
    text_color: str | None,
) -> None:
    line = {"name": "U2", "product": "subway", "color": line_color}
    result = Departure.from_dict(departure(line=line)).to_dict(
        show_api_line_colors, walking_time=1
    )

    assert result["color"] == color
    assert result["text_color"] == text_color


@pytest.mark.parametrize(
    ("stop", "configured_stop_id", "other_stop_name"),
    [
        (location(STOP_ID, STOP_NAME), STOP_ID, None),
        # YAML stores the stop id as a number, the API returns a string.
        (location(STOP_ID, STOP_NAME), int(STOP_ID), None),
        (NEARBY_STOP, STOP_ID, "S Schönhauser Allee"),
        (NEARBY_STOP, None, None),
    ],
)
def test_to_dict_other_stop_name(
    stop: dict[str, str],
    configured_stop_id: str | int | None,
    other_stop_name: str | None,
) -> None:
    result = Departure.from_dict(departure(stop=stop)).to_dict(
        show_api_line_colors=False, walking_time=1, stop_id=configured_stop_id
    )

    assert result["other_stop_name"] == other_stop_name


def test_departures_from_two_requests_are_deduplicated() -> None:
    # The Ringbahn passes both directions of a direction filter.
    first = Departure.from_dict(departure("S41", product="suburban"))
    second = Departure.from_dict(departure("S41", product="suburban"))

    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_hash_follows_shown_fields() -> None:
    on_time = Departure.from_dict(departure())
    delayed = Departure.from_dict(departure(delay=60))

    assert hash(on_time) != hash(delayed)


def test_hash_ignores_order_of_warnings() -> None:
    warnings = [
        {"type": "warning", "id": "1", "summary": "Construction"},
        {"type": "warning", "id": "2", "summary": "Elevator out of order"},
    ]
    first = Departure.from_dict(departure(remarks=warnings))
    second = Departure.from_dict(departure(remarks=warnings[::-1]))

    assert hash(first) == hash(second)
