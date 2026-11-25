import pytest

from septa_detours.geo import distance_to_line_m

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
