"""Tests for match/walk.py: walking a detour one street at a time.

Coordinates are hand-built near 17th & Washington (lon ~ -75, lat ~ 40),
so a lon/lat swap shows.
"""

import math

import polars as pl
import pytest

from septa_detours.geo import EARTH_RADIUS_M
from septa_detours.match.walk import street_graph
from septa_detours.streets.load import STREET_WAYS_SCHEMA

LON, LAT = -75.1716, 39.9385
STEP = 0.001
"""0.001 deg: ~111.2 m north-south, ~85.2 m east-west here."""

NORTH_SOUTH_M = EARTH_RADIUS_M * math.radians(STEP)
EAST_WEST_M = NORTH_SOUTH_M * math.cos(math.radians(LAT))


def make_ways(ways: list[tuple[int, list[tuple[int, float, float]]]]) -> pl.DataFrame:
    """A street-cache frame from ``(way_id, [(node_id, lon, lat), ...])``."""
    rows = [
        (
            way_id,
            f"Street {way_id}",
            "residential",
            [node_id for node_id, _, _ in nodes],
            [[lon, lat] for _, lon, lat in nodes],
        )
        for way_id, nodes in ways
    ]
    return pl.DataFrame(rows, schema=STREET_WAYS_SCHEMA, orient="row")


def selected(*way_ids: int) -> pl.DataFrame:
    return pl.DataFrame({"way_id": list(way_ids)}, schema={"way_id": pl.Int64})


# Way 1 runs east along LAT: nodes 10, 11, 12. Way 2 continues it from 12
# to 13. Way 3 runs north through 11 (a cross street). Way 4 is elsewhere.
WAYS = make_ways(
    [
        (1, [(10, LON, LAT), (11, LON + STEP, LAT), (12, LON + 2 * STEP, LAT)]),
        (2, [(12, LON + 2 * STEP, LAT), (13, LON + 3 * STEP, LAT)]),
        (
            3,
            [
                (30, LON + STEP, LAT - STEP),
                (11, LON + STEP, LAT),
                (31, LON + STEP, LAT + STEP),
            ],
        ),
        (
            4,
            [
                (40, LON + 9 * STEP, LAT + 9 * STEP),
                (41, LON + 9 * STEP, LAT + 8 * STEP),
            ],
        ),
    ]
)


def edges(graph) -> dict[tuple[int, int], float]:
    """Each edge as ``(smaller node, larger node) -> length_m``."""
    return {
        (min(a, b), max(a, b)): data["length_m"]
        for a, b, data in graph.edges(data=True)
    }


def test_ways_sharing_an_end_node_join_into_one_street() -> None:
    graph = street_graph(WAYS, selected(1, 2))
    assert sorted(graph.nodes) == [10, 11, 12, 13]
    assert edges(graph) == {
        (10, 11): pytest.approx(EAST_WEST_M),
        (11, 12): pytest.approx(EAST_WEST_M),
        (12, 13): pytest.approx(EAST_WEST_M),
    }


def test_lengths_are_metres_north_south_too() -> None:
    graph = street_graph(WAYS, selected(3))
    assert edges(graph) == {
        (11, 30): pytest.approx(NORTH_SOUTH_M),
        (11, 31): pytest.approx(NORTH_SOUTH_M),
    }


def test_nodes_carry_lon_and_lat() -> None:
    graph = street_graph(WAYS, selected(2))
    assert dict(graph.nodes(data=True)) == {
        12: {"lon": LON + 2 * STEP, "lat": LAT},
        13: {"lon": LON + 3 * STEP, "lat": LAT},
    }


def test_crossing_ways_share_their_node() -> None:
    graph = street_graph(WAYS, selected(1, 3))
    assert sorted(graph.neighbors(11)) == [10, 12, 30, 31]


def test_only_selected_ways() -> None:
    graph = street_graph(WAYS, selected(4))
    assert sorted(graph.nodes) == [40, 41]
    assert list(graph.edges) == [(40, 41)]


def test_no_way_selected_gives_an_empty_graph() -> None:
    graph = street_graph(WAYS, selected())
    assert graph.number_of_nodes() == 0


def test_one_node_way_is_a_lone_node() -> None:
    ways = make_ways([(1, [(10, LON, LAT)])])
    graph = street_graph(ways, selected(1))
    assert dict(graph.nodes(data=True)) == {10: {"lon": LON, "lat": LAT}}
    assert graph.number_of_edges() == 0


def test_selected_needs_only_a_way_id_column() -> None:
    # street_matches output has a specificity column too: ignored.
    matches = pl.DataFrame({"way_id": [2], "specificity": [3]})
    assert sorted(street_graph(WAYS, matches).nodes) == [12, 13]


def test_diagonal_length_uses_the_mean_latitude() -> None:
    # 0.1 deg each way: long enough that the latitude used for the
    # east-west scale shows (one end's vs the mean: ~0.3% apart).
    ways = make_ways([(1, [(10, LON, LAT), (11, LON + 0.1, LAT + 0.1)])])
    east_west = math.radians(0.1) * math.cos(math.radians(LAT + 0.05))
    expected = EARTH_RADIUS_M * math.hypot(east_west, math.radians(0.1))
    assert edges(street_graph(ways, selected(1))) == {
        (10, 11): pytest.approx(expected, rel=1e-9)
    }
