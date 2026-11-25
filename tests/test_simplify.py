import copy
import math

import pytest

from septa_detours.export.simplify import simplify_line

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
