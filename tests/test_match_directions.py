"""Tests for ``match.directions.find_direction_id``.

Rows are copied from the real 2026-11-25 ``directions.txt`` files, except
where a test says it builds a hypothetical one. Frames are built with
``directions_from_rows`` (conftest).
"""

from collections.abc import Callable

import polars as pl
import pytest

from septa_detours.match.directions import COMPASS_NAMES, find_direction_id

type DirectionsFromRows = Callable[
    [list[tuple[str, str, int, str | None]]], pl.DataFrame
]


@pytest.fixture
def directions(directions_from_rows: DirectionsFromRows) -> pl.DataFrame:
    return directions_from_rows(
        [
            ("bus", "55", 0, "Northbound"),
            ("bus", "55", 1, "Southbound"),
            ("bus", "21", 0, "Eastbound"),
            ("bus", "21", 1, "Westbound"),
            # 0 is West here: direction_id order is per route.
            ("bus", "64", 0, "Westbound"),
            ("bus", "64", 1, "Eastbound"),
            ("bus", "68", 0, "Northbound"),
            ("bus", "68", 1, "Southbound"),
            ("bus", "310", 0, "Loop"),
            # Single-row route, and its only direction_id is 0.
            ("bus", "409", 0, "Southbound"),
            ("rail", "AIR", 0, "Inbound"),
            ("rail", "AIR", 1, "Outbound"),
        ]
    )


def test_compass_names_are_pinned():
    """Exact spellings used in ``directions.txt`` (all 316 compass rows)."""
    expected = {
        "NB": "Northbound",
        "SB": "Southbound",
        "EB": "Eastbound",
        "WB": "Westbound",
    }
    assert expected == COMPASS_NAMES


@pytest.mark.parametrize(
    ("route_id", "direction", "expected"),
    [
        ("55", "NB", 0),
        ("55", "SB", 1),
        ("21", "EB", 0),
        ("21", "WB", 1),
        ("64", "WB", 0),
        ("64", "EB", 1),
        ("409", "SB", 0),
    ],
)
def test_finds_direction_id(
    directions: pl.DataFrame, route_id: str, direction, expected: int
):
    assert find_direction_id(directions, "bus", route_id, direction) == expected


def test_returns_plain_int(directions: pl.DataFrame):
    """``AffectedShape.direction_id`` is a strict ``int``."""
    assert type(find_direction_id(directions, "bus", "55", "SB")) is int


def test_direction_not_on_route_raises(directions: pl.DataFrame):
    """Route 68 runs N/S; its message says "EB Via Tinicum" (a street)."""
    with pytest.raises(ValueError, match="68") as excinfo:
        find_direction_id(directions, "bus", "68", "EB")
    expected = "bus route '68' has no Eastbound direction (has Northbound, Southbound)"
    assert str(excinfo.value) == expected


def test_loop_route_raises(directions: pl.DataFrame):
    with pytest.raises(ValueError, match=r"has no Northbound direction \(has Loop\)$"):
        find_direction_id(directions, "bus", "310", "NB")


def test_single_row_route_missing_direction_raises(directions: pl.DataFrame):
    with pytest.raises(ValueError, match=r"\(has Southbound\)$"):
        find_direction_id(directions, "bus", "409", "NB")


def test_unknown_route_raises(directions: pl.DataFrame):
    with pytest.raises(
        ValueError, match=r"^bus route '999' has no Southbound direction \(has none\)$"
    ):
        find_direction_id(directions, "bus", "999", "SB")


def test_other_feed_is_ignored(directions_from_rows: DirectionsFromRows):
    """A rail row never answers for a bus route with the same ``route_id``."""
    directions = directions_from_rows([("rail", "21", 0, "Eastbound")])
    with pytest.raises(ValueError, match=r"\(has none\)$"):
        find_direction_id(directions, "bus", "21", "EB")


def test_other_route_is_ignored(directions: pl.DataFrame):
    """Route 21's Eastbound doesn't satisfy route 55."""
    with pytest.raises(ValueError, match=r"\(has Northbound, Southbound\)$"):
        find_direction_id(directions, "bus", "55", "EB")


@pytest.mark.parametrize(
    "spelling", ["northbound", "Northbound ", "North", "Northbound Express"]
)
def test_direction_name_match_is_exact(
    spelling: str, directions_from_rows: DirectionsFromRows
):
    """Hypothetical near-miss spellings: not SEPTA's, so no match."""
    directions = directions_from_rows([("bus", "55", 0, spelling)])
    with pytest.raises(ValueError, match="has no Northbound direction"):
        find_direction_id(directions, "bus", "55", "NB")


def test_duplicate_direction_raises(directions_from_rows: DirectionsFromRows):
    """Hypothetical: both direction_ids named Eastbound. Don't pick one."""
    directions = directions_from_rows(
        [("bus", "21", 0, "Eastbound"), ("bus", "21", 1, "Eastbound")]
    )
    with pytest.raises(
        ValueError, match=r"^bus route '21' has 2 Eastbound directions$"
    ):
        find_direction_id(directions, "bus", "21", "EB")


def test_null_direction_names_are_skipped_in_message(
    directions_from_rows: DirectionsFromRows,
):
    """Hypothetical null name: not listed, and doesn't crash the message."""
    directions = directions_from_rows(
        [("bus", "55", 0, None), ("bus", "55", 1, "Southbound")]
    )
    with pytest.raises(ValueError, match=r"\(has Southbound\)$"):
        find_direction_id(directions, "bus", "55", "NB")
