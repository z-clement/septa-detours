"""Tests for ``septa_detours.streets.cache``."""

import polars as pl
import pytest

from septa_detours.streets.cache import combine_street_ways
from septa_detours.streets.load import STREET_WAYS_SCHEMA

# Real-looking Philly [lon, lat] points.
A = [-75.1679, 39.9396]
B = [-75.1677, 39.9386]
C = [-75.1675, 39.9376]

BROAD = (101, "South Broad Street", "primary", [1, 2], [A, B])
WASHINGTON = (102, "Washington Avenue", "secondary", [2, 3], [B, C])
STATION = (107, "Station Drive", "service", [3, 1], [C, A])
TURNPIKE = (110, "Pennsylvania Turnpike", "motorway", [1, 3], [A, C])


def ways(*rows: tuple) -> pl.DataFrame:
    """A frame shaped like ``read_street_ways`` output."""
    return pl.DataFrame(list(rows), schema=STREET_WAYS_SCHEMA, orient="row")


def test_disjoint_frames_stack_in_order():
    combined = combine_street_ways([ways(BROAD, WASHINGTON), ways(STATION)])
    assert combined.rows() == [BROAD, WASHINGTON, STATION]
    assert combined.schema == STREET_WAYS_SCHEMA


def test_frame_order_decides_row_order():
    combined = combine_street_ways([ways(STATION), ways(BROAD, WASHINGTON)])
    assert combined.rows() == [STATION, BROAD, WASHINGTON]


def test_identical_way_in_two_frames_kept_once_at_first_position():
    """A border road: same way, same content, in PA and in DE."""
    combined = combine_street_ways(
        [ways(BROAD, TURNPIKE, WASHINGTON), ways(STATION, TURNPIKE)]
    )
    assert combined.rows() == [BROAD, TURNPIKE, WASHINGTON, STATION]


def test_identical_way_in_three_frames_kept_once():
    combined = combine_street_ways(
        [ways(TURNPIKE), ways(BROAD, TURNPIKE), ways(TURNPIKE, STATION)]
    )
    assert combined.rows() == [TURNPIKE, BROAD, STATION]


def test_single_frame_unchanged():
    assert combine_street_ways([ways(BROAD, WASHINGTON)]).rows() == [BROAD, WASHINGTON]


def test_empty_frames_give_empty_typed_frame():
    combined = combine_street_ways([ways(), ways()])
    assert combined.is_empty()
    assert combined.schema == STREET_WAYS_SCHEMA


def test_empty_frame_among_others_is_harmless():
    assert combine_street_ways([ways(), ways(BROAD), ways()]).rows() == [BROAD]


def test_no_frames_is_a_caller_bug():
    with pytest.raises(ValueError, match="empty"):
        combine_street_ways([])


@pytest.mark.parametrize(
    "edited",
    [
        (110, "Pennsylvania Tpke", "motorway", [1, 3], [A, C]),  # renamed
        (110, "Pennsylvania Turnpike", "trunk", [1, 3], [A, C]),  # reclassified
        (110, "Pennsylvania Turnpike", "motorway", [1, 2, 3], [A, B, C]),  # node added
        (110, "Pennsylvania Turnpike", "motorway", [1, 3], [A, [-75.1675, 39.9377]]),
    ],
    ids=["name", "highway", "nodes", "moved-node"],
)
def test_same_way_id_with_different_content_raises(edited):
    with pytest.raises(
        ValueError, match=r"^1 OSM ways differ between extracts \(way 110\)"
    ):
        combine_street_ways([ways(BROAD, TURNPIKE), ways(edited, STATION)])


def test_conflict_within_one_frame_also_raises():
    edited = (101, "Broad Street", *BROAD[2:])
    with pytest.raises(ValueError, match=r"\(way 101\)"):
        combine_street_ways([ways(BROAD, edited)])


def test_conflict_message_lists_five_ids_then_counts_the_rest():
    first = ways(*[(i, "Old Name", "residential", [1, 2], [A, B]) for i in range(1, 8)])
    second = ways(
        *[(i, "New Name", "residential", [1, 2], [A, B]) for i in range(1, 8)]
    )
    with pytest.raises(ValueError, match="re-fetch") as excinfo:
        combine_street_ways([first, second])
    assert str(excinfo.value).startswith(
        "7 OSM ways differ between extracts (way 1, 2, 3, 4, 5 and 2 more)"
    )


def test_conflict_message_with_exactly_five_ids_has_no_more():
    first = ways(*[(i, "Old Name", "residential", [1, 2], [A, B]) for i in range(1, 6)])
    second = ways(
        *[(i, "New Name", "residential", [1, 2], [A, B]) for i in range(1, 6)]
    )
    with pytest.raises(ValueError, match=r"\(way 1, 2, 3, 4, 5\);"):
        combine_street_ways([first, second])
