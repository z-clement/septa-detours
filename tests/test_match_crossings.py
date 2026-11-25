import polars as pl
import pytest

from septa_detours.match.crossings import (
    CROSSING_RADIUS_M,
    ROUTE_RADIUS_M,
    Crossing,
    crossings_near_route,
    distance_to_line_m,
    find_crossings,
)
from septa_detours.streets.load import STREET_WAYS_SCHEMA

# Near 17th & Washington. At this latitude 0.0001 deg is ~11.1 m north-south
# and ~8.5 m east-west.
LON, LAT = -75.1716, 39.9385


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


def test_one_shared_node() -> None:
    ways = make_ways(
        [
            (1, [(10, LON - 0.001, LAT), (11, LON, LAT), (12, LON + 0.001, LAT)]),
            (2, [(20, LON, LAT - 0.001), (11, LON, LAT), (21, LON, LAT + 0.001)]),
        ]
    )
    assert find_crossings(ways, selected(1), selected(2)) == (
        Crossing(node_ids=(11,), node_id=11, lon=LON, lat=LAT),
    )


def test_no_shared_node() -> None:
    ways = make_ways(
        [(1, [(10, LON, LAT), (11, LON + 0.001, LAT)]), (2, [(20, LON, LAT + 0.001)])]
    )
    assert find_crossings(ways, selected(1), selected(2)) == ()


@pytest.mark.parametrize(("first", "second"), [((), (2,)), ((1,), ()), ((), ())])
def test_empty_side(first: tuple[int, ...], second: tuple[int, ...]) -> None:
    ways = make_ways([(1, [(11, LON, LAT)]), (2, [(11, LON, LAT)])])
    assert find_crossings(ways, selected(*first), selected(*second)) == ()


def test_only_selected_ways_count() -> None:
    # Way 3 shares node 11 with way 1, but isn't on either side.
    ways = make_ways(
        [
            (1, [(11, LON, LAT), (12, LON + 0.001, LAT)]),
            (2, [(12, LON + 0.001, LAT), (20, LON + 0.001, LAT + 0.001)]),
            (3, [(11, LON, LAT), (30, LON, LAT - 0.001)]),
        ]
    )
    assert [c.node_id for c in find_crossings(ways, selected(1), selected(2))] == [12]


def test_node_on_several_ways_of_a_side_counts_once() -> None:
    # Node 11 ends way 1 and starts way 3 (both "first"), and is on way 2.
    ways = make_ways(
        [
            (1, [(10, LON - 0.001, LAT), (11, LON, LAT)]),
            (3, [(11, LON, LAT), (12, LON + 0.001, LAT)]),
            (2, [(20, LON, LAT - 0.001), (11, LON, LAT)]),
            (4, [(11, LON, LAT), (21, LON, LAT + 0.001)]),
        ]
    )
    assert find_crossings(ways, selected(1, 3), selected(2, 4)) == (
        Crossing(node_ids=(11,), node_id=11, lon=LON, lat=LAT),
    )


def test_wide_crossing_is_one_group_with_middle_representative() -> None:
    # A divided road: three shared nodes ~22 m apart north-south. The middle
    # one is nearest the average, though it has the largest ID.
    north, middle, south = (LON, LAT + 0.0002), (LON, LAT), (LON, LAT - 0.0002)
    ways = make_ways(
        [
            (1, [(5, *north), (6, *south), (99, *middle)]),
            (2, [(5, *north), (99, *middle), (6, *south)]),
        ]
    )
    assert find_crossings(ways, selected(1), selected(2)) == (
        Crossing(node_ids=(5, 6, 99), node_id=99, lon=middle[0], lat=middle[1]),
    )


def test_representative_tie_goes_to_smaller_node_id() -> None:
    # Two nodes exactly equally far from their average. Coordinates are
    # binary-exact (multiples of 2**-12 deg, ~27 m), so float rounding can't
    # make one fractionally nearer and hide the tie-break.
    step = 2**-12
    lon, lat = -75.171875, 39.9375
    for north_id, south_id in [(8, 7), (7, 8)]:
        nodes = [(north_id, lon, lat + 2 * step), (south_id, lon, lat)]
        ways = make_ways([(1, nodes), (2, nodes)])
        (crossing,) = find_crossings(ways, selected(1), selected(2))
        assert crossing.node_ids == (7, 8)
        assert crossing.node_id == 7


def test_far_apart_groups_stay_separate_in_node_id_order() -> None:
    # Same pair of names in two towns, ~11 km apart. The far group has the
    # smaller node ID and comes first, though its way is listed last.
    far = (LON, LAT + 0.1)
    ways = make_ways(
        [
            (1, [(50, LON, LAT)]),
            (2, [(50, LON, LAT)]),
            (3, [(40, *far)]),
            (4, [(40, *far)]),
        ]
    )
    assert find_crossings(ways, selected(1, 3), selected(2, 4)) == (
        Crossing(node_ids=(40,), node_id=40, lon=far[0], lat=far[1]),
        Crossing(node_ids=(50,), node_id=50, lon=LON, lat=LAT),
    )


def test_single_linkage_chains() -> None:
    # 1 -> 2 and 2 -> 3 are ~89 m apart, 1 -> 3 ~178 m: still one group.
    points = [(1, LON, LAT), (2, LON, LAT + 0.0008), (3, LON, LAT + 0.0016)]
    ways = make_ways([(10, points), (20, points)])
    (crossing,) = find_crossings(ways, selected(10), selected(20))
    assert crossing.node_ids == (1, 2, 3)
    assert crossing.node_id == 2


def test_group_merges_two_earlier_groups() -> None:
    # Nodes are taken in ID order: 1 and 2 are ~178 m apart (two groups)
    # until node 3, between them, joins both.
    points = [(1, LON, LAT), (2, LON, LAT + 0.0016), (3, LON, LAT + 0.0008)]
    ways = make_ways([(10, points), (20, points)])
    assert find_crossings(ways, selected(10), selected(20)) == (
        Crossing(node_ids=(1, 2, 3), node_id=3, lon=LON, lat=LAT + 0.0008),
    )


@pytest.mark.parametrize(
    ("offset", "groups"),
    [
        # North-south: 0.0008 deg = 89 m (joined), 0.0010 deg = 111 m (not).
        ((0.0, 0.0008), 1),
        ((0.0, 0.0010), 2),
        # East-west: 0.0012 deg lon = 102 m at this latitude (not joined at
        # 100 m), 0.0011 deg = 94 m (joined). Without the cos(lat) factor
        # both would be over 100 m.
        ((0.0011, 0.0), 1),
        ((0.0012, 0.0), 2),
        # Diagonal: ~68 m east + ~67 m north = 95 m in a straight line
        # (joined), though the two legs add up to 135 m.
        ((0.0008, 0.0006), 1),
    ],
)
def test_grouping_radius_in_metres(offset: tuple[float, float], groups: int) -> None:
    other = (LON + offset[0], LAT + offset[1])
    points = [(1, LON, LAT), (2, *other)]
    ways = make_ways([(10, points), (20, points)])
    assert len(find_crossings(ways, selected(10), selected(20))) == groups


def test_custom_radius() -> None:
    points = [(1, LON, LAT), (2, LON, LAT + 0.0010)]  # ~111 m apart
    ways = make_ways([(10, points), (20, points)])
    assert len(find_crossings(ways, selected(10), selected(20), radius_m=120)) == 1
    assert len(find_crossings(ways, selected(10), selected(20), radius_m=100)) == 2


def test_default_radius_is_100_m() -> None:
    assert CROSSING_RADIUS_M == 100.0


# Worked out by hand from the mean Earth radius (1 deg = 111,195 m): at
# LAT, 0.001 deg of longitude is 85.27 m and 0.001 deg of latitude 111.20 m.
EAST_M = 85.27
NORTH_M = 111.20


def test_distance_on_a_vertex_is_zero() -> None:
    line = [[LON - 0.001, LAT], [LON, LAT], [LON + 0.001, LAT]]
    assert distance_to_line_m(LON, LAT, line) == 0


def test_distance_inside_a_segment_is_zero() -> None:
    line = [[LON - 0.001, LAT], [LON + 0.001, LAT]]
    assert distance_to_line_m(LON, LAT, line) == pytest.approx(0, abs=1e-6)


def test_distance_is_perpendicular_not_to_a_vertex() -> None:
    # A north-south line 0.001 deg east; its vertices are farther away
    # (~140 m) than the line itself.
    line = [[LON + 0.001, LAT - 0.001], [LON + 0.001, LAT + 0.001]]
    assert distance_to_line_m(LON, LAT, line) == pytest.approx(EAST_M, rel=1e-3)


@pytest.mark.parametrize(
    "line",
    [
        [[LON, LAT + 0.001], [LON, LAT + 0.002]],  # point is before the start
        [[LON, LAT + 0.002], [LON, LAT + 0.001]],  # ... or past the end
    ],
)
def test_distance_clamps_to_segment_end(line: list[list[float]]) -> None:
    assert distance_to_line_m(LON, LAT, line) == pytest.approx(NORTH_M, rel=1e-3)


def test_distance_uses_nearest_segment_anywhere_in_line() -> None:
    line = [
        [LON + 0.01, LAT + 0.01],
        [LON + 0.01, LAT + 0.005],
        [LON + 0.001, LAT - 0.001],  # nearest segment is the last one
        [LON + 0.001, LAT + 0.001],
    ]
    assert distance_to_line_m(LON, LAT, line) == pytest.approx(EAST_M, rel=1e-3)


def test_distance_to_single_point_line() -> None:
    line = [[LON + 0.001, LAT + 0.001]]
    expected = (EAST_M**2 + NORTH_M**2) ** 0.5
    assert distance_to_line_m(LON, LAT, line) == pytest.approx(expected, rel=1e-3)


def test_distance_with_repeated_vertex() -> None:
    # A zero-length segment (duplicate shape point) is just a point.
    line = [[LON, LAT + 0.001], [LON, LAT + 0.001], [LON, LAT + 0.002]]
    assert distance_to_line_m(LON, LAT, line) == pytest.approx(NORTH_M, rel=1e-3)


def test_distance_rejects_empty_line() -> None:
    with pytest.raises(ValueError, match="empty line"):
        distance_to_line_m(LON, LAT, [])


def crossing_at(node_id: int, lon: float, lat: float) -> Crossing:
    return Crossing(node_ids=(node_id,), node_id=node_id, lon=lon, lat=lat)


# A north-south route line through (LON, LAT).
ROUTE_LINE = [[LON, LAT - 0.01], [LON, LAT + 0.01]]


def test_near_route_keeps_close_drops_far_in_input_order() -> None:
    near_b = crossing_at(2, LON + 0.004, LAT)  # ~341 m east
    far = crossing_at(1, LON + 0.02, LAT)  # ~1.7 km east (another town)
    near_a = crossing_at(3, LON, LAT + 0.005)  # on the line
    assert crossings_near_route([near_b, far, near_a], [ROUTE_LINE]) == (
        near_b,
        near_a,
    )


def test_near_route_any_line_counts() -> None:
    # Far from the first line, close to the second (the other direction).
    crossing = crossing_at(1, LON + 0.02, LAT)
    other_line = [[LON + 0.02, LAT - 0.01], [LON + 0.02, LAT + 0.01]]
    assert crossings_near_route([crossing], [ROUTE_LINE, other_line]) == (crossing,)


@pytest.mark.parametrize(
    ("east_deg", "kept"),
    [
        (0.0058, True),  # ~495 m
        (0.0059, False),  # ~503 m
    ],
)
def test_near_route_default_radius_is_500_m(east_deg: float, kept: bool) -> None:
    crossing = crossing_at(1, LON + east_deg, LAT)
    assert crossings_near_route([crossing], [ROUTE_LINE]) == (
        (crossing,) if kept else ()
    )
    assert ROUTE_RADIUS_M == 500.0


def test_near_route_custom_radius() -> None:
    crossing = crossing_at(1, LON + 0.001, LAT)  # ~85 m
    assert crossings_near_route([crossing], [ROUTE_LINE], radius_m=90) == (crossing,)
    assert crossings_near_route([crossing], [ROUTE_LINE], radius_m=80) == ()


def test_near_route_no_lines_or_no_crossings() -> None:
    assert crossings_near_route([crossing_at(1, LON, LAT)], []) == ()
    assert crossings_near_route([], [ROUTE_LINE]) == ()
