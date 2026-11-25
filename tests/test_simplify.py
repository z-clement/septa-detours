import copy
import math

import pytest

from septa_detours.export.simplify import covering_shapes, round_line, simplify_line

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
