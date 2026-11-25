import json
import re
from collections.abc import Callable

import pytest

from septa_detours.parse.notice import SOURCE_KEY_LENGTH, make_source_key

OLD = "2026-11-25T025344Z"
NEW = "2026-11-25T121123Z"

ROUTE_31 = "bus_route_31"
BROAD_WALNUT = "Broad & Walnut"  # route 31 #4
START_31_4 = "11/25/2026   3:00 PM"


def route_key_fields(
    read_alert_fixture: Callable[[str], bytes], stamp: str, route_id: str
) -> list[tuple[str, str, str]]:
    """``(route_id, location_start, start)`` for each detour item in a fixture."""
    route = json.loads(read_alert_fixture(f"{stamp}__{route_id}.json"))
    return [
        (route["route_id"], item["location_start"], item["start"])
        for item in route["detour"]
    ]


# --- make_source_key -------------------------------------------------------


def test_source_key_is_short_lowercase_hex() -> None:
    key = make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4)
    assert re.fullmatch(rf"[0-9a-f]{{{SOURCE_KEY_LENGTH}}}", key)


def test_source_key_is_pinned() -> None:
    """Keys are compared across snapshots parsed at different times, so the
    algorithm must not drift silently. Update this only on purpose."""
    assert make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4) == "661b7024a25d2bbd"


@pytest.mark.parametrize("index", range(5))
def test_source_key_same_detour_across_snapshots(
    read_alert_fixture: Callable[[str], bytes], index: int
) -> None:
    """Route 31 items 0-4 appear unchanged in both snapshots."""
    old = route_key_fields(read_alert_fixture, OLD, ROUTE_31)[index]
    new = route_key_fields(read_alert_fixture, NEW, ROUTE_31)[index]
    assert make_source_key(*old) == make_source_key(*new)


def test_source_key_distinct_detours_differ(
    read_alert_fixture: Callable[[str], bytes],
) -> None:
    """All 7 route 31 items in the newer snapshot get different keys
    (#3 and #4 share a start; #5 and #6 share a start)."""
    keys = [
        make_source_key(*f) for f in route_key_fields(read_alert_fixture, NEW, ROUTE_31)
    ]
    assert len(keys) == 7
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize(
    ("route_id", "location_start", "start"),
    [
        ("bus_route_32", BROAD_WALNUT, START_31_4),
        (ROUTE_31, "Broad & Chestnut", START_31_4),
        (ROUTE_31, BROAD_WALNUT, "11/25/2026   3:01 PM"),
    ],
)
def test_source_key_every_field_counts(
    route_id: str, location_start: str, start: str
) -> None:
    base = make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4)
    assert make_source_key(route_id, location_start, start) != base


@pytest.mark.parametrize(
    ("route_id", "location_start", "start"),
    [
        # Whitespace: runs collapse, ends are stripped, in every field.
        (ROUTE_31, "Broad &  Walnut", START_31_4),
        (ROUTE_31, " Broad & Walnut\u00a0", START_31_4),
        (ROUTE_31, BROAD_WALNUT, "11/25/2026 3:00 PM"),
        (f" {ROUTE_31}\t", BROAD_WALNUT, START_31_4),
        # Case, in every field.
        (ROUTE_31, "BROAD & walnut", START_31_4),
        (ROUTE_31, BROAD_WALNUT, "11/25/2026   3:00 pm"),
        ("BUS_ROUTE_31", BROAD_WALNUT, START_31_4),
    ],
)
def test_source_key_ignores_cosmetic_edits(
    route_id: str, location_start: str, start: str
) -> None:
    base = make_source_key(ROUTE_31, BROAD_WALNUT, START_31_4)
    assert make_source_key(route_id, location_start, start) == base


def test_source_key_keeps_inner_spaces() -> None:
    """Whitespace collapses to one space; it isn't removed."""
    spaced = make_source_key(ROUTE_31, "Broad & Walnut", START_31_4)
    glued = make_source_key(ROUTE_31, "Broad &Walnut", START_31_4)
    assert spaced != glued


def test_source_key_does_not_normalize_times() -> None:
    """Only whitespace and case are forgiven, not zero-padding."""
    assert make_source_key(
        ROUTE_31, BROAD_WALNUT, "11/25/2026 3:00 PM"
    ) != make_source_key(ROUTE_31, BROAD_WALNUT, "11/25/2026 03:00 PM")


def test_source_key_blank_equals_whitespace_only() -> None:
    """Route 64 #1/#2 have blank locations; spaces-only reads as blank."""
    assert make_source_key("bus_route_64", "", START_31_4) == make_source_key(
        "bus_route_64", "   ", START_31_4
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Text moved between fields must not collide.
        ((ROUTE_31, "Broad &", "Walnut"), (ROUTE_31, "Broad", "& Walnut")),
        ((ROUTE_31, "a|b", "c"), (ROUTE_31, "a", "b|c")),
        ((ROUTE_31, "", "x"), (ROUTE_31, "x", "")),
    ],
)
def test_source_key_field_boundaries_matter(
    first: tuple[str, str, str], second: tuple[str, str, str]
) -> None:
    assert make_source_key(*first) != make_source_key(*second)
