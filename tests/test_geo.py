import math

import pytest

from septa_detours.geo import EARTH_RADIUS_M, distance_to_line_m, metres_between

# Near 17th & Washington.
LON, LAT = -75.1716, 39.9385

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


# metres_between: [lon, lat] points near 17th & Washington.
LON, LAT = -75.1716, 39.9385
DEGREE_M = EARTH_RADIUS_M * math.radians(1)


def test_metres_between_same_point_is_zero() -> None:
    assert metres_between([LON, LAT], [LON, LAT]) == 0


def test_metres_between_north_south() -> None:
    assert metres_between([LON, LAT], [LON, LAT + 0.001]) == pytest.approx(
        0.001 * DEGREE_M, rel=1e-9
    )


def test_metres_between_east_west_shrinks_with_latitude() -> None:
    assert metres_between([LON, LAT], [LON + 0.001, LAT]) == pytest.approx(
        0.001 * DEGREE_M * math.cos(math.radians(LAT)), rel=1e-9
    )


def test_metres_between_diagonal_uses_the_mean_latitude() -> None:
    # 0.1 deg each way: one end's latitude would be ~0.3% off.
    east_west = 0.1 * DEGREE_M * math.cos(math.radians(LAT + 0.05))
    assert metres_between([LON, LAT], [LON + 0.1, LAT + 0.1]) == pytest.approx(
        math.hypot(east_west, 0.1 * DEGREE_M), rel=1e-9
    )


def test_metres_between_is_symmetric_and_takes_tuples() -> None:
    a, b = (LON, LAT), (LON + 0.003, LAT - 0.002)
    assert metres_between(a, b) == metres_between(b, a)
