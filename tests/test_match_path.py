"""Tests for match/path.py: a detour's path from its steps.

A hand-built grid near 17th & Washington (lon ~ -75, lat ~ 40): 17th and
Broad run north-south, Washington and Reed east-west. Route 2's real
detour has this shape: "SB via 17th, Left on Washington, Right on Broad,
Right on Passyunk, Left on 17th, Reg Rt" (Reed stands in for Passyunk,
which runs diagonally).
"""

import polars as pl
import pytest

from septa_detours.match.path import (
    DetourPath,
    Leg,
    detour_path,
    walk_to_route,
    walk_turns,
)
from septa_detours.match.streets import street_key_table
from septa_detours.model import StartPoint, Step, Turn
from septa_detours.streets.load import STREET_WAYS_SCHEMA

LON, LAT = -75.1716, 39.9385
STEP = 0.001
"""One grid block: ~85 m east-west, ~111 m north-south."""


def node(x: int, y: int) -> int:
    """The node ID at grid point ``(x, y)`` (x east, y north; -1..3)."""
    return 1000 + 10 * (x + 1) + (y + 2)


def point(x: int, y: int) -> tuple[float, float]:
    return (LON + x * STEP, LAT + y * STEP)


def make_ways(ways: list[tuple[int, str, list[tuple[int, int]]]]) -> pl.DataFrame:
    """A street-cache frame from ``(way_id, osm_name, [(x, y), ...])``."""
    rows = [
        (
            way_id,
            name,
            "residential",
            [node(x, y) for x, y in grid],
            [list(point(x, y)) for x, y in grid],
        )
        for way_id, name, grid in ways
    ]
    return pl.DataFrame(rows, schema=STREET_WAYS_SCHEMA, orient="row")


SOUTH = [2, 1, 0, -1, -2]
EAST = [-1, 0, 1, 2, 3]
GRID = make_ways(
    [
        (1, "South 17th Street", [(0, y) for y in SOUTH]),
        (2, "South Broad Street", [(2, y) for y in SOUTH]),
        (3, "Washington Avenue", [(x, 0) for x in EAST]),
        (4, "Reed Street", [(x, -1) for x in EAST]),
    ]
)
KEYS = street_key_table(GRID)
START = node(0, 0)  # 17th & Washington


def steps(*pairs: tuple[Turn, str]) -> list[Step]:
    return [Step(turn=turn, street=street) for turn, street in pairs]


ROUTE_2 = steps(
    ("via", "17th"),
    ("left", "Washington"),
    ("right", "Broad"),
    ("right", "Reed"),
    ("left", "17th"),
)


def leg(street: str, *grid: tuple[int, int]) -> Leg:
    return Leg(
        street=street,
        nodes=tuple(node(x, y) for x, y in grid),
        points=tuple(point(x, y) for x, y in grid),
    )


def test_route_2_walks_each_street_to_the_next() -> None:
    assert walk_turns(ROUTE_2, {START}, GRID, KEYS) == (
        (
            leg("Washington", (0, 0), (1, 0), (2, 0)),
            leg("Broad", (2, 0), (2, -1)),
            leg("Reed", (2, -1), (1, -1), (0, -1)),
        ),
        frozenset({node(0, -1)}),
    )


def test_two_steps_have_no_legs() -> None:
    path = steps(("via", "17th"), ("left", "Washington"))
    assert walk_turns(path, {START}, GRID, KEYS) == ((), frozenset({START}))


def test_a_turn_against_the_message_is_no_path() -> None:
    # East on Washington, then south on Broad: a right, not a left.
    wrong = [*ROUTE_2[:2], Step(turn="left", street="Broad"), *ROUTE_2[3:]]
    assert walk_turns(wrong, {START}, GRID, KEYS) is None


def test_the_first_turn_is_not_checked_here() -> None:
    # Onto Washington from the route: the caller's job (needs the route).
    first_wrong = [ROUTE_2[0], Step(turn="right", street="Washington"), *ROUTE_2[2:]]
    assert walk_turns(first_wrong, {START}, GRID, KEYS) is not None


@pytest.mark.parametrize(
    "path",
    [
        # Washington and Reed never cross.
        steps(
            ("via", "17th"), ("left", "Washington"), ("right", "Reed"), ("left", "17th")
        ),
        # No such street.
        steps(
            ("via", "17th"), ("left", "Walnut"), ("right", "Broad"), ("left", "17th")
        ),
        steps(
            ("via", "17th"),
            ("left", "Washington"),
            ("right", "Walnut"),
            ("left", "17th"),
        ),
    ],
)
def test_streets_that_dont_meet_are_no_path(path: list[Step]) -> None:
    assert walk_turns(path, {START}, GRID, KEYS) is None


def test_start_off_the_first_street_is_no_path() -> None:
    # Broad & Reed isn't on Washington.
    assert walk_turns(ROUTE_2, {node(2, -1)}, GRID, KEYS) is None


def test_nearest_crossing_from_the_start() -> None:
    # From Washington at x=-1, east: 17th is the first crossing, not Broad.
    path = steps(("via", "Reed"), ("left", "Washington"), ("right", "17th"))
    assert walk_turns(path, {node(-1, 0)}, GRID, KEYS) == (
        (leg("Washington", (-1, 0), (0, 0)),),
        frozenset({node(0, 0)}),
    )


def extra_way(way_id: int, name: str, nodes: list[tuple[int, float, float]]):
    """One more way with free node IDs and points: ``(node, lon, lat)``."""
    return pl.DataFrame(
        [
            (
                way_id,
                name,
                "residential",
                [n for n, _, _ in nodes],
                [[lon, lat] for _, lon, lat in nodes],
            )
        ],
        schema=STREET_WAYS_SCHEMA,
        orient="row",
    )


def test_next_leg_starts_from_the_nearest_node_of_a_wide_crossing() -> None:
    # A Washington slip road joins Broad at node 5000, ~55 m north of the
    # main corner: the crossing has two nodes. Heading north to Federal,
    # the Broad leg starts at the slip road's node, the nearer one.
    slip = (5000, LON + 2 * STEP, LAT + 0.5 * STEP)
    broad = [(node(2, y), *point(2, y)) for y in (2, 1)]
    broad += [slip] + [(node(2, y), *point(2, y)) for y in (0, -1, -2)]
    ways = pl.concat(
        [
            GRID.filter(pl.col("way_id") != 2),
            extra_way(2, "South Broad Street", broad),
            extra_way(5, "Washington Avenue", [(node(1, 0), *point(1, 0)), slip]),
            extra_way(6, "Federal Street", [(node(x, 1), *point(x, 1)) for x in EAST]),
        ]
    )
    path = steps(
        ("via", "17th"), ("left", "Washington"), ("left", "Broad"), ("left", "Federal")
    )
    result = walk_turns(path, {START}, ways, street_key_table(ways))
    assert result is not None
    legs, corner = result
    assert [leg.nodes for leg in legs] == [
        (node(0, 0), node(1, 0), node(2, 0)),
        (5000, node(2, 1)),
    ]
    assert corner == frozenset({node(2, 1)})


def test_a_turn_that_cant_be_told_is_accepted() -> None:
    # Passyunk runs diagonally through 17th & Washington: the Washington
    # leg is one node (the turn off it is at the corner it turned on at),
    # so the turn onto Passyunk can't be told, whatever the message says.
    passyunk = [(node(x, -x), *point(x, -x)) for x in (-1, 0, 1)]
    ways = pl.concat([GRID, extra_way(5, "East Passyunk Avenue", passyunk)])
    path = steps(
        ("via", "17th"),
        ("left", "Washington"),
        ("right", "Passyunk"),
        ("right", "Reed"),
    )
    result = walk_turns(path, {START}, ways, street_key_table(ways))
    assert result is not None
    legs, corner = result
    assert [leg.nodes for leg in legs] == [(START,), (START, node(1, -1))]
    assert corner == frozenset({node(1, -1)})


# walk_to_route. Route lines as [lon, lat] lists, along grid streets.
ON_17TH = [list(point(0, 2)), list(point(0, -2))]
ON_BROAD = [list(point(2, 2)), list(point(2, -2))]


def test_known_rejoin_at_the_corner_is_a_one_node_leg() -> None:
    # Route 2: "..., Right on Reed, Left on 17th": back on 17th at Reed.
    rejoin = node(0, -1)
    assert walk_to_route(ROUTE_2, {rejoin}, GRID, KEYS, [ON_17TH], rejoin) == leg(
        "17th", (0, -1)
    )


def test_known_rejoin_further_along_the_last_street() -> None:
    assert walk_to_route(
        ROUTE_2, {node(0, -1)}, GRID, KEYS, [ON_17TH], node(0, -2)
    ) == leg("17th", (0, -1), (0, -2))


def test_known_rejoin_off_the_last_street_is_no_leg() -> None:
    assert (
        walk_to_route(ROUTE_2, {node(0, -1)}, GRID, KEYS, [ON_17TH], node(2, -1))
        is None
    )


# Route on Broad; the detour comes down 17th and turns onto Reed, which
# isn't the route: Reed is walked east until it's back on Broad.
VIA_BROAD = steps(
    ("via", "Broad"), ("right", "Washington"), ("left", "17th"), ("left", "Reed")
)


def test_no_rejoin_walks_the_last_street_back_to_the_route() -> None:
    assert walk_to_route(VIA_BROAD, {node(0, -1)}, GRID, KEYS, [ON_BROAD], None) == leg(
        "Reed", (0, -1), (1, -1), (2, -1)
    )


def test_no_rejoin_the_route_counts_within_the_rejoin_radius() -> None:
    # A line 0.0002 deg (~17 m) east of Broad: Broad's nodes are in reach.
    near = [[lon + 0.0002, lat] for lon, lat in ON_BROAD]
    assert walk_to_route(VIA_BROAD, {node(0, -1)}, GRID, KEYS, [near], None) == leg(
        "Reed", (0, -1), (1, -1), (2, -1)
    )
    # ~51 m east (0.0006 deg): out of reach, and so is x=3 (~34 m beyond).
    far = [[lon + 0.0006, lat] for lon, lat in ON_BROAD]
    assert walk_to_route(VIA_BROAD, {node(0, -1)}, GRID, KEYS, [far], None) is None


def test_no_rejoin_any_line_will_do() -> None:
    assert walk_to_route(
        VIA_BROAD, {node(0, -1)}, GRID, KEYS, [ON_17TH[:1] * 2, ON_BROAD], None
    ) == leg("Reed", (0, -1), (1, -1), (2, -1))


def test_no_rejoin_and_no_lines_is_no_leg() -> None:
    assert walk_to_route(VIA_BROAD, {node(0, -1)}, GRID, KEYS, [], None) is None


def test_no_rejoin_from_a_corner_on_the_route_is_no_leg() -> None:
    # "via 17th, Left on Washington": the corner is on 17th, the route; where
    # the bus gets back on isn't said. (Washington meets 17th only there.)
    path = steps(("via", "17th"), ("left", "Washington"))
    assert walk_to_route(path, {START}, GRID, KEYS, [ON_17TH], None) is None
    # Even when the street reaches the route again further on.
    assert walk_to_route(path, {START}, GRID, KEYS, [ON_17TH, ON_BROAD], None) is None


def test_corner_may_be_any_iterable() -> None:
    corner = (n for n in [node(0, -1)])
    assert walk_to_route(VIA_BROAD, corner, GRID, KEYS, [ON_BROAD], None) == leg(
        "Reed", (0, -1), (1, -1), (2, -1)
    )


# detour_path.


def start_at(x: int, y: int) -> StartPoint:
    lon, lat = point(x, y)
    return StartPoint(node_id=node(x, y), lon=lon, lat=lat)


def test_route_2_path_to_its_known_rejoin() -> None:
    rejoin = start_at(0, -1)
    path = detour_path(ROUTE_2, start_at(0, 0), rejoin, GRID, KEYS, [ON_17TH])
    assert path == DetourPath(
        line=tuple(
            point(x, y) for x, y in [(0, 0), (1, 0), (2, 0), (2, -1), (1, -1), (0, -1)]
        ),
        rejoin=rejoin,
    )


def test_path_without_a_rejoin_finds_one() -> None:
    # From Broad & Washington: west, down 17th, east on Reed back to Broad.
    path = detour_path(VIA_BROAD, start_at(2, 0), None, GRID, KEYS, [ON_BROAD])
    assert path == DetourPath(
        line=tuple(
            point(x, y) for x, y in [(2, 0), (1, 0), (0, 0), (0, -1), (1, -1), (2, -1)]
        ),
        rejoin=start_at(2, -1),
    )


def test_the_turn_onto_the_last_street_must_agree() -> None:
    # South on 17th, then east on Reed: a left.
    wrong = [*VIA_BROAD[:-1], Step(turn="right", street="Reed")]
    assert detour_path(wrong, start_at(2, 0), None, GRID, KEYS, [ON_BROAD]) is None


def test_a_rejoin_at_the_start_counts_as_none() -> None:
    # Round the block back to 17th & Washington, the start: tier B's rejoin
    # would be the start itself. Without it, the corner is on the route.
    loop = [
        *ROUTE_2[:4],
        Step(turn="right", street="17th"),
        Step(turn="right", street="Washington"),
    ]
    start = start_at(0, 0)
    assert detour_path(loop, start, start, GRID, KEYS, [ON_17TH]) is None


@pytest.mark.parametrize(
    "path",
    [
        [],
        steps(("via", "17th")),
        # A middle street that doesn't reach the next one.
        steps(
            ("via", "17th"), ("left", "Washington"), ("right", "Reed"), ("left", "17th")
        ),
    ],
)
def test_no_path(path: list[Step]) -> None:
    assert (
        detour_path(path, start_at(0, 0), start_at(0, -1), GRID, KEYS, [ON_17TH])
        is None
    )


def test_last_street_failing_is_no_path() -> None:
    # The known rejoin isn't on 17th.
    assert (
        detour_path(ROUTE_2, start_at(0, 0), start_at(2, -2), GRID, KEYS, [ON_17TH])
        is None
    )


def test_a_single_point_is_no_path() -> None:
    # Node 9999 sits exactly on the start (OSM has such duplicates): walking
    # to it goes nowhere.
    lon, lat = point(0, 0)
    ways = pl.concat(
        [GRID, extra_way(5, "Washington Avenue", [(START, lon, lat), (9999, lon, lat)])]
    )
    rejoin = StartPoint(node_id=9999, lon=lon, lat=lat)
    two = steps(("via", "17th"), ("left", "Washington"))
    keys = street_key_table(ways)
    assert walk_to_route(two, {START}, ways, keys, [ON_17TH], 9999) == Leg(
        "Washington", (START, 9999), (point(0, 0), point(0, 0))
    )
    assert detour_path(two, start_at(0, 0), rejoin, ways, keys, [ON_17TH]) is None
