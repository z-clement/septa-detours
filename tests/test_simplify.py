import copy
import math

import pytest

from septa_detours.export.simplify import (
    covering_shapes,
    cut_along,
    distinct_pieces,
    round_line,
    simplify_line,
)
from septa_detours.geo import EARTH_RADIUS_M

# Near 17th & Washington. Worked out by hand from the mean Earth radius
# (1 deg = 111,195 m): 0.00005 deg of latitude is 5.56 m; 0.00007 deg of
# longitude is 5.97 m at this latitude (7.78 m if the cos(lat) scale were
# forgotten).
LON, LAT = -75.1716, 39.9385
WEST = [LON - 0.001, LAT]
EAST = [LON + 0.001, LAT]


def test_two_point_line_is_unchanged() -> None:
    line = [[LON, LAT], [LON + 0.001, LAT + 0.001]]
    assert simplify_line(line, 1000) == line


def test_straight_line_collapses_to_its_endpoints() -> None:
    line = [[LON + step * 0.001, LAT] for step in range(5)]
    assert simplify_line(line, 1) == [line[0], line[-1]]


def test_diagonal_line_collapses_to_its_endpoints() -> None:
    line = [[LON + step * 0.001, LAT + step * 0.002] for step in range(5)]
    assert simplify_line(line, 1) == [line[0], line[-1]]


@pytest.mark.parametrize(("tolerance_m", "kept"), [(5, True), (6, False)])
def test_bump_north_kept_only_above_tolerance(tolerance_m: float, kept: bool) -> None:
    bump = [LON, LAT + 0.00005]  # 5.56 m off the line
    expected = [WEST, bump, EAST] if kept else [WEST, EAST]
    assert simplify_line([WEST, bump, EAST], tolerance_m) == expected


@pytest.mark.parametrize(("tolerance_m", "kept"), [(5.5, True), (6.5, False)])
def test_bump_east_uses_the_latitude_scale(tolerance_m: float, kept: bool) -> None:
    south, north = [LON, LAT - 0.001], [LON, LAT + 0.001]
    bump = [LON + 0.00007, LAT]  # 5.97 m off the line
    expected = [south, bump, north] if kept else [south, north]
    assert simplify_line([south, bump, north], tolerance_m) == expected


def test_scale_is_taken_at_the_mean_latitude() -> None:
    # A 2-degree north-south line: 0.0001 deg of longitude at its middle
    # (40 deg) is 8.52 m; at its first point's latitude (39 deg) 8.64 m.
    south, north = [LON, 39.0], [LON, 41.0]
    bump = [LON + 0.0001, 40.0]
    assert simplify_line([south, bump, north], 8.58) == [south, north]


def test_tie_for_farthest_splits_at_the_earlier_point() -> None:
    # Both bumps are exactly 11.1 m off the first chord. Splitting at the
    # first leaves the second 2.2 m off the new chord (dropped); splitting
    # at the second would leave the first 5.5 m off (kept).
    first, second = [LON + 0.001, LAT + 0.0001], [LON + 0.002, LAT + 0.0001]
    end = [LON + 0.006, LAT]
    line = [[LON, LAT], first, second, end]
    assert simplify_line(line, 4) == [[LON, LAT], first, end]


def test_point_exactly_at_tolerance_is_dropped() -> None:
    # A repeated point is exactly 0 m off the line: a binary-exact tie.
    assert simplify_line([WEST, WEST, EAST], 0) == [WEST, EAST]


def test_zero_tolerance_keeps_a_tiny_bump() -> None:
    bump = [LON, LAT + 0.0000001]  # ~1 cm
    assert simplify_line([WEST, bump, EAST], 0) == [WEST, bump, EAST]


def test_loop_keeps_its_far_side() -> None:
    # First and last points are the same: there is no line through them,
    # only a point, so the far side is measured from that point (111 m).
    far = [LON, LAT + 0.001]
    assert simplify_line([WEST, far, WEST], 100) == [WEST, far, WEST]


def test_loop_inside_tolerance_keeps_both_ends() -> None:
    far = [LON, LAT + 0.001]
    assert simplify_line([WEST, far, WEST], 200) == [WEST, WEST]


def test_point_on_the_first_chord_is_kept_after_a_split() -> None:
    # Points 1 and 3 lie exactly on the first-to-last chord, but once the
    # peak is kept they are ~67 m off the new chords on either side.
    line = [[LON + step * 0.001, LAT] for step in range(5)]
    line[2] = [LON + 0.002, LAT + 0.002]
    assert simplify_line(line, 10) == line


def test_does_not_change_its_input_or_share_points() -> None:
    line = [WEST, [LON, LAT + 0.001], EAST]
    before = copy.deepcopy(line)
    result = simplify_line(line, 0)
    result[0][0] = 0.0
    assert line == before


def test_accepts_tuples_and_returns_lists() -> None:
    line = ((LON, LAT), (LON + 0.001, LAT))
    assert simplify_line(line, 1) == [[LON, LAT], [LON + 0.001, LAT]]


@pytest.mark.parametrize("line", [[], [[LON, LAT]]])
def test_rejects_lines_under_two_points(line: list[list[float]]) -> None:
    with pytest.raises(ValueError, match=f"at least 2 points, got {len(line)}"):
        simplify_line(line, 5)


@pytest.mark.parametrize("tolerance_m", [-1, math.nan])
def test_rejects_negative_or_nan_tolerance(tolerance_m: float) -> None:
    with pytest.raises(ValueError, match="tolerance_m must be >= 0"):
        simplify_line([WEST, EAST], tolerance_m)


# round_line. Raw GTFS-like coordinates and what they round to at 5
# decimals; the *_NEAR points round to the same position as their partner.
A_RAW, A_NEAR, A = (
    [-75.171634, 39.938512],
    [-75.171628, 39.938508],
    [-75.17163, 39.93851],
)
B_RAW, B_NEAR, B = [-75.170001, 39.939104], [-75.169998, 39.939096], [-75.17, 39.9391]


def test_round_line_rounds_each_coordinate() -> None:
    assert round_line([A_RAW, B_RAW], 5) == [A, B]


def test_round_line_uses_decimals() -> None:
    assert round_line([A_RAW, B_RAW], 3) == [[-75.172, 39.939], [-75.17, 39.939]]


def test_round_line_drops_a_repeat_created_by_rounding() -> None:
    assert round_line([A_RAW, A_NEAR, B_RAW], 5) == [A, B]


def test_round_line_drops_a_repeat_at_the_end() -> None:
    assert round_line([A_RAW, B_RAW, B_NEAR], 5) == [A, B]


def test_round_line_drops_a_run_of_repeats() -> None:
    assert round_line([A_RAW, A_NEAR, A_RAW, B_RAW], 5) == [A, B]


def test_round_line_keeps_a_repeat_further_along() -> None:
    # A loop back to the start is not a zero-length segment.
    assert round_line([A_RAW, B_RAW, A_NEAR], 5) == [A, B, A]


def test_round_line_keeps_a_point_differing_only_in_latitude() -> None:
    same_lon = [A_RAW[0], B_RAW[1]]
    assert round_line([A_RAW, same_lon, B_RAW], 5) == [A, [A[0], B[1]], B]


def test_round_line_collapsed_line_keeps_two_separate_points() -> None:
    result = round_line([A_RAW, A_NEAR], 5)
    assert result == [A, A]
    result[0][0] = 0.0
    assert result[1] == A


def test_round_line_does_not_change_its_input() -> None:
    line = [A_RAW.copy(), B_RAW.copy()]
    result = round_line(line, 5)
    result[0][0] = 0.0
    assert line == [A_RAW, B_RAW]


def test_round_line_accepts_tuples_and_returns_lists() -> None:
    assert round_line((tuple(A_RAW), tuple(B_RAW)), 5) == [A, B]


@pytest.mark.parametrize("line", [[], [A_RAW]])
def test_round_line_rejects_lines_under_two_points(line: list[list[float]]) -> None:
    with pytest.raises(ValueError, match=f"at least 2 points, got {len(line)}"):
        round_line(line, 5)


# covering_shapes. Lines on a grid of 0.001 deg steps from (LON, LAT):
# one step east is 85.27 m, one step north 111.20 m.
def grid(*steps: tuple[float, float]) -> list[list[float]]:
    return [[LON + x * 0.001, LAT + y * 0.001] for x, y in steps]


MAIN = grid((0, 0), (1, 0), (2, 0), (3, 0), (4, 0))  # 341 m east


def test_covering_no_lines() -> None:
    assert covering_shapes({}) == []


def test_covering_one_line_is_kept() -> None:
    assert covering_shapes({"317337": MAIN}) == ["317337"]


def test_covering_drops_a_short_turn() -> None:
    short = grid((0, 0), (1, 0), (2, 0))
    assert covering_shapes({"short": short, "main": MAIN}) == ["main"]


def test_covering_keeps_a_branch_after_the_longer_line() -> None:
    branch = grid((0, 0), (1, 0), (1, 1), (1, 2))  # 307 m, turns north
    assert covering_shapes({"branch": branch, "main": MAIN}) == ["main", "branch"]


def test_covering_drops_a_line_stitched_from_two_kept_lines() -> None:
    # Neither kept line alone covers "stitched": its first points lie on
    # "main" only, its last points on "branch" only.
    main = grid(*((x, 0) for x in range(7)))  # 512 m
    branch = grid((0, 0), (1, 0), (1, 1), (1, 2), (1, 3))  # 418 m
    stitched = grid((3, 0), (2, 0), (1, 0), (1, 1), (1, 2))  # 392 m
    lines = {"stitched": stitched, "branch": branch, "main": main}
    assert covering_shapes(lines) == ["main", "branch"]


def test_covering_ignores_direction_of_travel() -> None:
    backwards = grid((3, 0), (2, 0), (1, 0), (0, 0))
    assert covering_shapes({"backwards": backwards, "main": MAIN}) == ["main"]


@pytest.mark.parametrize(
    ("ids", "expected"), [(("a", "b"), ["a"]), (("b", "a"), ["b"])]
)
def test_covering_equal_lengths_keep_input_order(
    ids: tuple[str, str], expected: list[str]
) -> None:
    assert covering_shapes(dict.fromkeys(ids, MAIN)) == expected


@pytest.mark.parametrize(
    ("north", "kept"), [(0.17, False), (0.19, True), (-0.17, False), (-0.19, True)]
)
def test_covering_tolerance_beside_a_line(north: float, kept: bool) -> None:
    # 0.17 steps north or south is 18.9 m, 0.19 steps 21.1 m: outside
    # MAIN's bare (zero-height) bounding box either way.
    nearby = grid((0, north), (1, north), (2, north))
    expected = ["main", "nearby"] if kept else ["main"]
    assert covering_shapes({"main": MAIN, "nearby": nearby}) == expected


@pytest.mark.parametrize(
    ("tail", "kept"),
    [
        ([(3, 0), (4.2, 0)], False),  # 17.1 m past the east end
        ([(3, 0), (4.25, 0)], True),  # 21.3 m past it
        ([(1, 0), (-0.2, 0)], False),  # 17.1 m before the west start
        ([(1, 0), (-0.25, 0)], True),  # 21.3 m before it
    ],
)
def test_covering_tolerance_past_the_ends_of_a_line(
    tail: list[tuple[float, float]], kept: bool
) -> None:
    expected = ["main", "tail"] if kept else ["main"]
    assert covering_shapes({"main": MAIN, "tail": grid(*tail)}) == expected


def test_covering_exactly_at_tolerance_counts_as_drawn() -> None:
    # Points on MAIN's vertices are exactly 0 m away: a binary-exact tie.
    on_vertices = grid((1, 0), (2, 0), (3, 0))
    assert covering_shapes({"main": MAIN, "on": on_vertices}, 0) == ["main"]


def test_covering_default_tolerance_is_20_m() -> None:
    near = grid((0, 0.17), (1, 0.17))  # 18.9 m
    far = grid((2, 0.19), (3, 0.19))  # 21.1 m
    lines = {"main": MAIN, "near": near, "far": far}
    assert covering_shapes(lines) == ["main", "far"]


@pytest.mark.parametrize("tolerance_m", [-1, math.nan])
def test_covering_rejects_negative_or_nan_tolerance(tolerance_m: float) -> None:
    with pytest.raises(ValueError, match="tolerance_m must be >= 0"):
        covering_shapes({"main": MAIN}, tolerance_m)


def test_covering_rejects_a_line_under_two_points() -> None:
    with pytest.raises(ValueError, match="shape '317338' has 1 point"):
        covering_shapes({"main": MAIN, "317338": [[LON, LAT]]})


# distinct_pieces, on the same grid as covering_shapes.


def test_pieces_first_line_is_kept_whole() -> None:
    assert distinct_pieces([MAIN]) == [(0, MAIN)]


def test_pieces_no_lines() -> None:
    assert distinct_pieces([]) == []


def test_pieces_a_copy_digitized_a_metre_away_adds_nothing() -> None:
    # Route 79 on Snyder: shapes ~1 m apart (0.00001 deg north).
    copy_ = [[lon, lat + 0.00001] for lon, lat in MAIN]
    assert distinct_pieces([MAIN, copy_]) == [(0, MAIN)]


# Where a line crosses the 20 m buffer north of MAIN, in grid steps.
EDGE = 20.0 / (EARTH_RADIUS_M * math.pi / 180) / 0.001


def pieces_approx(pieces):
    """``pieces`` with every coordinate as ``pytest.approx`` (1 mm)."""
    return [
        (index, [pytest.approx(point, abs=1e-8) for point in piece])
        for index, piece in pieces
    ]


def test_pieces_a_branch_keeps_its_own_part_joined_to_the_trunk() -> None:
    # Leaves MAIN at (1, 0): from the buffer's edge (EDGE north) on, plus the
    # joint on MAIN.
    branch = grid((0, 0), (1, 0), (1, 1), (1, 2))
    assert distinct_pieces([MAIN, branch]) == pieces_approx(
        [(0, MAIN), (1, grid((1, 0), (1, EDGE), (1, 1), (1, 2)))]
    )


def test_pieces_a_line_joining_the_trunk_keeps_its_approach() -> None:
    joining = grid((0, 2), (0, 1), (0, 0), (1, 0))
    assert distinct_pieces([MAIN, joining]) == pieces_approx(
        [(0, MAIN), (1, grid((0, 2), (0, 1), (0, EDGE), (0, 0)))]
    )


def test_pieces_a_loop_off_the_trunk_and_back() -> None:
    # Leaves at (1, 0), back at (2, 0), on to (3, 0): only the loop.
    loop = grid((0, 0), (1, 0), (1, 1), (2, 1), (2, 0), (3, 0))
    assert distinct_pieces([MAIN, loop]) == pieces_approx(
        [(0, MAIN), (1, grid((1, 0), (1, EDGE), (1, 1), (2, 1), (2, EDGE), (2, 0)))]
    )


def test_pieces_two_separate_divergences_are_two_pieces() -> None:
    line = grid((0, 0), (0, 1), (1, 1), (1, 0), (2, 0), (2, 1), (3, 1), (3, 0))
    assert distinct_pieces([MAIN, line]) == pieces_approx(
        [
            (0, MAIN),
            (1, grid((0, 0), (0, EDGE), (0, 1), (1, 1), (1, EDGE), (1, 0))),
            (1, grid((2, 0), (2, EDGE), (2, 1), (3, 1), (3, EDGE), (3, 0))),
        ]
    )


def test_pieces_keep_travel_order() -> None:
    # Southbound, joining MAIN's east end from the north.
    south = grid((4, 2), (4, 1), (4, 0), (3, 0))
    assert distinct_pieces([MAIN, south]) == pieces_approx(
        [(0, MAIN), (1, grid((4, 2), (4, 1), (4, EDGE), (4, 0)))]
    )


def test_pieces_a_straight_trunk_splits_where_the_branch_turns() -> None:
    # The trunk has no point at the turn (x = 2): the cut is made there
    # anyway, not at the trunk's last point before it.
    branch = grid((0, 0), (2, 0), (2, 3))  # longer: drawn first, whole
    trunk = grid((0, 0), (4, 0))
    [_, (index, piece)] = distinct_pieces([branch, trunk])
    assert index == 1
    # Starts at the joint on the branch, then the buffer's edge ~20 m east.
    assert piece[0] == pytest.approx(grid((2, 0))[0], abs=1e-8)
    east_of_turn = (piece[1][0] - grid((2, 0))[0][0]) / 0.001 * 85.27
    assert east_of_turn == pytest.approx(20.0, abs=0.1)
    assert piece[-1] == grid((4, 0))[0]


def test_pieces_compare_with_every_earlier_line() -> None:
    # The third line runs on MAIN, then on the branch: nothing new.
    branch = grid((1, 0), (1, 1), (1, 2), (1, 3))
    third = grid((3, 0), (2, 0), (1, 0), (1, 1), (1, 2))
    assert [index for index, _ in distinct_pieces([MAIN, branch, third])] == [0, 1]


@pytest.mark.parametrize(("north", "kept"), [(0.17, False), (0.19, True)])
def test_pieces_tolerance(north: float, kept: bool) -> None:
    # 0.17 steps is 18.9 m, 0.19 steps 21.1 m.
    nearby = grid((0, north), (1, north), (2, north))
    expected = [(0, MAIN), (1, nearby)] if kept else [(0, MAIN)]
    assert distinct_pieces([MAIN, nearby]) == expected


def test_pieces_tolerance_is_a_parameter() -> None:
    nearby = grid((0, 0.17), (1, 0.17), (2, 0.17))  # 18.9 m away
    assert distinct_pieces([MAIN, nearby], tolerance_m=10.0) == [(0, MAIN), (1, nearby)]


def test_pieces_are_new_lists() -> None:
    lines = [[tuple(point) for point in MAIN]]
    [(_, piece)] = distinct_pieces(lines)
    assert piece == MAIN
    assert all(isinstance(point, list) for point in piece)
    assert lines == [[tuple(point) for point in MAIN]]


def test_pieces_reject_bad_input() -> None:
    with pytest.raises(ValueError, match="line 1 has 1 point"):
        distinct_pieces([MAIN, MAIN[:1]])
    for tolerance in (0.0, -1.0, math.nan):
        with pytest.raises(ValueError, match="tolerance_m must be > 0"):
            distinct_pieces([MAIN], tolerance_m=tolerance)


# cut_along, on the same grid.


def approx_line(steps):
    return [pytest.approx(point, abs=1e-9) for point in grid(*steps)]


def test_cut_along_keeps_the_line_s_own_points_between_the_ends() -> None:
    assert cut_along([MAIN], grid((0.5, 0))[0], grid((3.2, 0))[0]) == approx_line(
        [(0.5, 0), (1, 0), (2, 0), (3, 0), (3.2, 0)]
    )


def test_cut_along_snaps_ends_a_little_off_the_line() -> None:
    # ~2.2 m north and south of MAIN: cut at the nearest points on it.
    start, end = grid((1.5, 0.02))[0], grid((2.5, -0.02))[0]
    assert cut_along([MAIN], start, end) == approx_line([(1.5, 0), (2, 0), (2.5, 0)])


def test_cut_along_needs_the_end_after_the_start() -> None:
    backwards = grid((4, 0), (0, 0))
    start, end = grid((1, 0))[0], grid((3, 0))[0]
    assert cut_along([MAIN], end, start) is None
    # The next line that runs that way is used.
    assert cut_along([MAIN, backwards], end, start) == approx_line([(3, 0), (1, 0)])


def test_cut_along_needs_both_ends_near_a_line() -> None:
    near, far = grid((1, 0))[0], grid((3, 0.1))[0]  # far: 11.1 m off
    assert cut_along([MAIN], near, far) is None
    assert cut_along([MAIN], near, far, max_gap_m=12.0) == approx_line(
        [(1, 0), (2, 0), (3, 0)]
    )


def test_cut_along_uses_the_first_line_that_has_both_ends() -> None:
    other = grid((0, 1), (4, 1))  # 111 m north: too far
    start, end = grid((1, 0))[0], grid((2, 0))[0]
    assert cut_along([other, MAIN], start, end) == approx_line([(1, 0), (2, 0)])
    assert cut_along([], start, end) is None


def test_cut_along_gap_limit_is_exact_enough() -> None:
    # 0.06 steps north is 6.7 m: over the default 5 m, under 10.
    start, end = grid((1, 0))[0], grid((3, 0.06))[0]
    assert cut_along([MAIN], start, end) is None


def test_cut_along_same_place_is_no_stretch() -> None:
    at = grid((2, 0))[0]
    assert cut_along([MAIN], at, at) is None


def test_cut_along_east_west_gaps_use_the_latitude_scale() -> None:
    # A north-south line; the end 0.06 steps east is 5.1 m off (6.7 m if
    # longitude weren't scaled by the latitude).
    north = grid((0, 0), (0, 4))
    start, end = grid((0, 1))[0], grid((0.06, 3))[0]
    assert cut_along([north], start, end, max_gap_m=6.0) == approx_line(
        [(0, 1), (0, 3)]
    )
