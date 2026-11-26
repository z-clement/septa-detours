"""Tests for match/walk.py: walking a detour one street at a time.

Coordinates are hand-built near 17th & Washington (lon ~ -75, lat ~ 40),
so a lon/lat swap shows.
"""

import math

import polars as pl
import pytest

from septa_detours.geo import EARTH_RADIUS_M
from septa_detours.match.walk import (
    TURN_LOOK_M,
    street_graph,
    turn_side,
    walk_street,
)
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


# walk_street: the street is ways 1 + 2 (10-11-12-13, east along LAT).
STREET = street_graph(WAYS, selected(1, 2))


@pytest.mark.parametrize(
    ("sources", "targets", "expected"),
    [
        # Along the street to the target, through the nodes between.
        ({10}, {12}, (10, 11, 12)),
        # Either way along it (undirected).
        ({13}, {10}, (13, 12, 11, 10)),
        # The nearest target: the first crossing, not a later one.
        ({10}, {13, 12}, (10, 11, 12)),
        # The nearest source: a wide crossing's other nodes are further.
        ({13, 10}, {11}, (10, 11)),
        # A source that's a target: the next turn is at the same corner.
        ({11}, {11, 13}, (11,)),
        # Nodes off the street are ignored, on either side.
        ({10, 30}, {31, 12}, (10, 11, 12)),
    ],
)
def test_walk_street(sources: set[int], targets: set[int], expected: tuple) -> None:
    assert walk_street(STREET, sources, targets) == expected


@pytest.mark.parametrize(
    ("sources", "targets"),
    [
        ({30, 31}, {12}),  # no source on the street
        ({10}, {30, 40}),  # no target on it
        ({10}, set()),
        (set(), {12}),
    ],
)
def test_walk_street_off_the_street(sources: set[int], targets: set[int]) -> None:
    assert walk_street(STREET, sources, targets) is None


def test_walk_street_unreachable_target() -> None:
    # Way 4 is in the graph but not connected to ways 1-2.
    graph = street_graph(WAYS, selected(1, 2, 4))
    assert walk_street(graph, {10}, {40}) is None
    assert walk_street(graph, {10}, {40, 13}) == (10, 11, 12, 13)


def test_walk_street_empty_graph() -> None:
    assert walk_street(street_graph(WAYS, selected()), {10}, {12}) is None


def test_walk_street_nearest_by_metres_not_by_nodes() -> None:
    # From 10: target 9 is one edge west but 5 steps away; target 12 is two
    # edges east but 2 steps away.
    ways = make_ways(
        [
            (1, [(9, LON - 5 * STEP, LAT), (10, LON, LAT)]),
            (2, [(10, LON, LAT), (11, LON + STEP, LAT), (12, LON + 2 * STEP, LAT)]),
        ]
    )
    assert walk_street(street_graph(ways, selected(1, 2)), {10}, {9, 12}) == (
        10,
        11,
        12,
    )


# Binary-exact halves: both edges from the middle node are exactly as long.
TIE_WAYS = make_ways([(1, [(1, -75.5, 40.0), (2, -75.0, 40.0), (3, -74.5, 40.0)])])


def test_walk_street_tie_is_not_guessed() -> None:
    graph = street_graph(TIE_WAYS, selected(1))
    assert walk_street(graph, {2}, {1, 3}) is None
    # Not a tie: one target only, or one nearer.
    assert walk_street(graph, {2}, {3}) == (2, 3)
    nearer = make_ways([(1, [(1, -75.5, 40.0), (2, -75.0, 40.0), (3, -74.25, 40.0)])])
    assert walk_street(street_graph(nearer, selected(1)), {2}, {1, 3}) == (2, 1)


def test_walk_street_takes_any_iterables() -> None:
    sources = (node for node in [10])
    targets = (node for node in [12, 12])
    assert walk_street(STREET, sources, targets) == (10, 11, 12)


# turn_side: the corner is (LON, LAT). STEP east is ~85 m, north ~111 m.
CORNER = [LON, LAT]
FROM_WEST = [[LON - STEP, LAT], CORNER]  # heading east
FROM_NORTH = [[LON, LAT + STEP], CORNER]  # heading south


@pytest.mark.parametrize(
    ("incoming", "outgoing", "expected"),
    [
        (FROM_WEST, [CORNER, [LON, LAT + STEP]], "left"),  # east, then north
        (FROM_WEST, [CORNER, [LON, LAT - STEP]], "right"),  # east, then south
        (FROM_NORTH, [CORNER, [LON + STEP, LAT]], "left"),  # south, then east
        (FROM_NORTH, [CORNER, [LON - STEP, LAT]], "right"),  # south, then west
    ],
)
def test_turn_side_square_corners(incoming, outgoing, expected: str) -> None:
    assert turn_side(incoming, outgoing) == expected


def test_turn_side_reads_past_a_misleading_first_segment() -> None:
    # Like 15th St -> South Penn Square: heading south, the new street
    # first runs ~44 m south and a touch west (a "right"), then ~170 m
    # east: a left turn.
    outgoing = [CORNER, [LON - 0.00002, LAT - 0.0004], [LON + 0.002, LAT - 0.0006]]
    assert turn_side(FROM_NORTH, outgoing) == "left"
    assert turn_side(FROM_NORTH, outgoing[:2]) == "right"


def test_turn_side_reads_only_so_far_back() -> None:
    # Heading east for the last ~170 m, but from 2.2 km north before that:
    # the whole incoming walk's chord points south, the bus heads east. A
    # turn to the north-west is left from east (right from south).
    incoming = [[LON - 0.002, LAT + 0.02], [LON - 0.002, LAT], CORNER]
    outgoing = [CORNER, [LON - 0.001, LAT + 0.002]]
    assert turn_side(incoming, outgoing) == "left"


def test_turn_side_look_distance() -> None:
    assert TURN_LOOK_M == 100.0
    # A first segment just under the look distance is passed over (99 m
    # south-west, then east); one just over it decides (101 m).
    for metres, expected in [(99.0, "left"), (101.0, "right")]:
        south = metres / NORTH_SOUTH_M * STEP
        outgoing = [CORNER, [LON - 0.000001, LAT - south], [LON + 0.01, LAT - south]]
        assert turn_side(FROM_NORTH, outgoing) == expected


@pytest.mark.parametrize(
    ("incoming", "outgoing"),
    [
        ([CORNER], [CORNER, [LON, LAT + STEP]]),  # incoming: one node
        (FROM_WEST, [CORNER]),  # outgoing: one node
        ([], []),
        ([], [CORNER, [LON, LAT + STEP]]),  # empty: no IndexError
        (FROM_WEST, []),
    ],
)
def test_turn_side_needs_two_points_each(incoming, outgoing) -> None:
    assert turn_side(incoming, outgoing) is None


def test_turn_side_straight_on_is_none() -> None:
    # Binary-exact: the cross product is exactly 0.
    assert (
        turn_side([[-75.5, 40.0], [-75.0, 40.0]], [[-75.0, 40.0], [-74.5, 40.0]])
        is None
    )


def test_turn_side_reads_back_past_a_short_last_segment() -> None:
    # The last ~25 m run east, the ~400 m before them north-east: read
    # over 100 m the bus heads north-east, and an east-north-east turn
    # from north-east is a right.
    incoming = [[LON - 0.003, LAT - 0.003], [LON - 0.0003, LAT], CORNER]
    outgoing = [CORNER, [LON + 0.002, LAT + 0.001]]
    assert turn_side(incoming, outgoing) == "right"


def test_turn_side_adds_up_short_segments() -> None:
    # Five ~33 m segments south and a touch west (together past 100 m),
    # then far east: read at 100 m, the bus has turned right (south-west).
    south = 0.0003
    outgoing = (
        [CORNER]
        + [[LON - 0.000001 * i, LAT - south * i] for i in range(1, 6)]
        + [[LON + 0.01, LAT - 5 * south]]
    )
    assert turn_side(FROM_NORTH, outgoing) == "right"
