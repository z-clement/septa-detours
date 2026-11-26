import polars as pl
import pytest

from septa_detours.match.place import (
    REJOIN_RADIUS_M,
    find_rejoin_point,
    find_start_point,
)
from septa_detours.match.streets import street_key_table
from septa_detours.model import Intersection, Segment, StartPoint, Step
from septa_detours.streets.load import STREET_WAYS_SCHEMA

# Near 17th & Washington. At this latitude 0.001 deg is ~111 m north-south
# and ~85 m east-west.
LON, LAT = -75.1716, 39.9385

# Route 2 runs north-south along 17th, through the crossing.
ROUTE_ON_17TH = [[LON, LAT - 0.002], [LON, LAT + 0.002]]

# ~850 m east of 17th: beyond the 500 m route radius.
ROUTE_FAR_EAST = [[LON + 0.01, LAT - 0.002], [LON + 0.01, LAT + 0.002]]

type Node = tuple[int, float, float]


def make_ways(ways: list[tuple[int, str, list[Node]]]) -> pl.DataFrame:
    """A street-cache frame from ``(way_id, osm_name, [(node, lon, lat)])``."""
    rows = [
        (
            way_id,
            name,
            "residential",
            [node_id for node_id, _, _ in nodes],
            [[lon, lat] for _, lon, lat in nodes],
        )
        for way_id, name, nodes in ways
    ]
    return pl.DataFrame(rows, schema=STREET_WAYS_SCHEMA, orient="row")


# 17th (north-south) and Washington (east-west) share node 11.
SEVENTEENTH_WASHINGTON = make_ways(
    [
        (
            1,
            "South 17th Street",
            [(10, LON, LAT - 0.001), (11, LON, LAT), (12, LON, LAT + 0.001)],
        ),
        (
            2,
            "Washington Avenue",
            [(20, LON - 0.001, LAT), (11, LON, LAT), (21, LON + 0.001, LAT)],
        ),
    ]
)


def place_intersection(
    streets: tuple[str, str],
    ways: pl.DataFrame,
    lines: list[list[list[float]]],
) -> tuple[StartPoint | None, tuple[str, ...]]:
    place = Intersection(streets=streets)
    return find_start_point(place, ways, street_key_table(ways), lines)


# --- Placed ---------------------------------------------------------------------


def test_one_crossing_near_route_is_the_start_point():
    result = place_intersection(
        ("17th St", "Washington Ave"), SEVENTEENTH_WASHINGTON, [ROUTE_ON_17TH]
    )
    assert result == (StartPoint(node_id=11, lon=LON, lat=LAT), ())


def test_name_order_does_not_matter():
    result = place_intersection(
        ("Washington", "17th"), SEVENTEENTH_WASHINGTON, [ROUTE_ON_17TH]
    )
    assert result == (StartPoint(node_id=11, lon=LON, lat=LAT), ())


def test_any_route_line_within_radius_counts():
    result = place_intersection(
        ("17th", "Washington"),
        SEVENTEENTH_WASHINGTON,
        [ROUTE_FAR_EAST, ROUTE_ON_17TH],
    )
    assert result == (StartPoint(node_id=11, lon=LON, lat=LAT), ())


def test_far_crossing_is_dropped_before_choosing():
    # Washington crosses 17th again ~1.1 km north, beyond the route's end.
    # Its node ID (5) is smaller, so it comes first in find_crossings'
    # order: taking the first crossing without the route check would pick it.
    ways = make_ways(
        [
            (1, "South 17th Street", [(11, LON, LAT), (5, LON, LAT + 0.01)]),
            (2, "Washington Avenue", [(20, LON - 0.001, LAT), (11, LON, LAT)]),
            (
                3,
                "Washington Avenue",
                [(30, LON - 0.001, LAT + 0.01), (5, LON, LAT + 0.01)],
            ),
        ]
    )
    result = place_intersection(("17th", "Washington"), ways, [ROUTE_ON_17TH])
    assert result == (StartPoint(node_id=11, lon=LON, lat=LAT), ())


def test_crossing_of_several_nodes_uses_its_representative_node():
    # Three Washington ways meet 17th ~33 m apart: one crossing (within the
    # 100 m grouping radius). Its representative is the node nearest the
    # group's average: the middle one, neither the first nor the last.
    joints = [(11, LON, LAT), (12, LON, LAT + 0.0003), (13, LON, LAT + 0.0006)]
    ways = make_ways(
        [
            (1, "South 17th Street", joints),
            *[
                (
                    node_id,
                    "Washington Avenue",
                    [(node_id + 100, lon - 0.001, lat), (node_id, lon, lat)],
                )
                for node_id, lon, lat in joints
            ],
        ]
    )
    result = place_intersection(("17th", "Washington"), ways, [ROUTE_ON_17TH])
    assert result == (StartPoint(node_id=12, lon=LON, lat=LAT + 0.0003), ())


# --- Not placed, no issue -----------------------------------------------------


def test_no_place_gives_no_point_and_no_issue():
    keys = street_key_table(SEVENTEENTH_WASHINGTON)
    result = find_start_point(None, SEVENTEENTH_WASHINGTON, keys, [ROUTE_ON_17TH])
    assert result == (None, ())


# --- Not placed, with an issue ------------------------------------------------


def test_segment_is_not_placed_yet():
    place = Segment(street="17th", between=("Washington", "Ellsworth"))
    keys = street_key_table(SEVENTEENTH_WASHINGTON)
    result = find_start_point(place, SEVENTEENTH_WASHINGTON, keys, [ROUTE_ON_17TH])
    assert result == (None, ("start: segments are not placed yet",))


def test_route_without_lines_is_an_issue():
    result = place_intersection(("17th", "Washington"), SEVENTEENTH_WASHINGTON, [])
    assert result == (None, ("start: route has no shapes to compare with",))


def test_unknown_street_names_the_streets_as_written():
    result = place_intersection(
        ("Garney St", "Washington Ave"), SEVENTEENTH_WASHINGTON, [ROUTE_ON_17TH]
    )
    assert result == (
        None,
        ("start: no crossing of 'Garney St' and 'Washington Ave' in OSM",),
    )


def test_streets_that_never_meet_are_an_issue():
    ways = make_ways(
        [
            (1, "South 17th Street", [(10, LON, LAT - 0.001), (12, LON, LAT + 0.001)]),
            (2, "Washington Avenue", [(20, LON - 0.001, LAT), (21, LON + 0.001, LAT)]),
        ]
    )
    result = place_intersection(("17th", "Washington"), ways, [ROUTE_ON_17TH])
    assert result == (
        None,
        ("start: no crossing of '17th' and 'Washington' in OSM",),
    )


def test_shared_ways_are_split_before_finding_crossings():
    # "Ridge" and "Ridge Ave" both match both Ridge Avenue ways. Without the
    # split, their joint (node 2) would be a crossing of a street with itself.
    ways = make_ways(
        [
            (1, "Ridge Avenue", [(1, LON, LAT - 0.001), (2, LON, LAT)]),
            (2, "Ridge Avenue", [(2, LON, LAT), (3, LON, LAT + 0.001)]),
        ]
    )
    result = place_intersection(("Ridge", "Ridge Ave"), ways, [ROUTE_ON_17TH])
    assert result == (None, ("start: no crossing of 'Ridge' and 'Ridge Ave' in OSM",))


def test_crossing_far_from_route_is_an_issue():
    result = place_intersection(
        ("17th", "Washington"), SEVENTEENTH_WASHINGTON, [ROUTE_FAR_EAST]
    )
    assert result == (
        None,
        ("start: no crossing of '17th' and 'Washington' within 500 m of the route",),
    )


@pytest.mark.parametrize("count", [2, 3])
def test_several_crossings_near_route_are_not_guessed(count):
    # Washington meets 17th every ~222 m (beyond the 100 m grouping radius),
    # all within 500 m of the route line.
    north = [LAT + 0.002 * i for i in range(count)]
    seventeenth = [(100 + i, LON, lat) for i, lat in enumerate(north)]
    washingtons = [
        (2 + i, "Washington Avenue", [(200 + i, LON - 0.001, lat), (100 + i, LON, lat)])
        for i, lat in enumerate(north)
    ]
    ways = make_ways([(1, "South 17th Street", seventeenth), *washingtons])
    result = place_intersection(("17th", "Washington"), ways, [ROUTE_ON_17TH])
    assert result == (
        None,
        (
            f"start: {count} crossings of '17th' and 'Washington'"
            " within 500 m of the route",
        ),
    )


# --- Rejoin (tier B) --------------------------------------------------------------


def rejoin(
    streets: list[str], ways: pl.DataFrame, lines: list[list[list[float]]]
) -> StartPoint | None:
    """``find_rejoin_point`` for a path of these streets (turns don't matter)."""
    steps = [
        Step(turn="via" if index == 0 else "left", street=street)
        for index, street in enumerate(streets)
    ]
    return find_rejoin_point(steps, ways, street_key_table(ways), lines)


# 2 m west of 17th, inside the rejoin radius; 50 m west, outside it.
# (0.001 deg of longitude is ~85 m here.)
ROUTE_2M_WEST = [[LON - 0.0000235, LAT - 0.002], [LON - 0.0000235, LAT + 0.002]]
ROUTE_50M_WEST = [[LON - 0.000588, LAT - 0.002], [LON - 0.000588, LAT + 0.002]]


def test_rejoin_is_the_last_two_streets_crossing_on_the_route():
    # Only the last two count: "Broad" isn't in the street data at all.
    point = rejoin(
        ["Broad", "Washington", "17th"], SEVENTEENTH_WASHINGTON, [ROUTE_ON_17TH]
    )
    assert point == StartPoint(node_id=11, lon=LON, lat=LAT)


def test_rejoin_within_its_radius_counts():
    assert REJOIN_RADIUS_M == 30.0
    point = rejoin(["Washington", "17th"], SEVENTEENTH_WASHINGTON, [ROUTE_2M_WEST])
    assert point == StartPoint(node_id=11, lon=LON, lat=LAT)


def test_rejoin_outside_its_radius_is_none():
    # 50 m is well inside the start radius (500 m), but not on the route.
    assert (
        rejoin(["Washington", "17th"], SEVENTEENTH_WASHINGTON, [ROUTE_50M_WEST]) is None
    )


def test_rejoin_checks_every_line():
    lines = [ROUTE_FAR_EAST, ROUTE_ON_17TH]
    point = rejoin(["Washington", "17th"], SEVENTEENTH_WASHINGTON, lines)
    assert point == StartPoint(node_id=11, lon=LON, lat=LAT)


@pytest.mark.parametrize(
    ("streets", "lines"),
    [
        (["17th"], [ROUTE_ON_17TH]),  # one step: nothing to cross
        ([], [ROUTE_ON_17TH]),
        (["Washington", "17th"], []),  # no shapes to be on
        (["Washington", "Broad"], [ROUTE_ON_17TH]),  # unknown street
        (["17th", "17th"], [ROUTE_ON_17TH]),  # a street never crosses itself
    ],
)
def test_no_rejoin(streets, lines):
    assert rejoin(streets, SEVENTEENTH_WASHINGTON, lines) is None


def test_several_rejoin_crossings_are_not_guessed():
    # Washington meets 17th twice, both on the route (a made-up loop).
    ways = make_ways(
        [
            (
                1,
                "South 17th Street",
                [(10, LON, LAT - 0.001), (11, LON, LAT), (12, LON, LAT + 0.001)],
            ),
            (2, "Washington Avenue", [(20, LON - 0.001, LAT), (11, LON, LAT)]),
            (3, "Washington Avenue", [(12, LON, LAT + 0.001), (30, LON + 0.001, LAT)]),
        ]
    )
    assert rejoin(["Washington", "17th"], ways, [ROUTE_ON_17TH]) is None


def test_rejoin_street_never_crosses_itself():
    # A short way whose two nodes (~4 m apart) would group into one
    # "crossing" if both names kept it.
    ways = make_ways(
        [(1, "South 17th Street", [(10, LON, LAT), (11, LON, LAT + 0.00004)])]
    )
    assert rejoin(["17th St", "17th"], ways, [ROUTE_ON_17TH]) is None
