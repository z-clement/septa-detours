"""Tests for match/skipped.py: the stretch of route a detour skips.

Coordinates are realistic Philadelphia ones (lon ~ -75, lat ~ 40), so a
lon/lat swap shows. At this latitude 0.001 deg is ~111 m north-south and
~85 m east-west.
"""

import pytest

from septa_detours.match.skipped import (
    MAX_STRETCH_RATIO,
    STRETCH_SLACK_M,
    skipped_stretch,
)

LON, LAT = -75.1716, 39.9385  # 17th & Washington
DEG_PER_M_EW = 0.001 / 85.2  # east-west, at this latitude
DEG_PER_M_NS = 0.001 / 111.0

# Route 2 SB-style shape along 17th, three points, in travel order (north).
ON_17TH = [[LON, LAT - 0.004], [LON, LAT], [LON, LAT + 0.004]]

# ~1 cm in degrees: pyproj round trips aren't bit-exact.
CM = 1e-7


def approx_line(line: list[list[float]]) -> list[list[float]]:
    return [pytest.approx(point, abs=CM) for point in line]  # ty: ignore


def test_stretch_between_the_two_points_keeps_the_shape_points_between():
    start = (LON, LAT - 0.002)
    rejoin = (LON, LAT + 0.001)
    assert skipped_stretch(ON_17TH, start, rejoin) == approx_line(
        [[LON, LAT - 0.002], [LON, LAT], [LON, LAT + 0.001]]
    )


def test_points_off_the_line_are_projected_onto_it():
    # The start 17 m east (a one-way pair), the rejoin 10 m west.
    start = (LON + 17 * DEG_PER_M_EW, LAT - 0.001)
    rejoin = (LON - 10 * DEG_PER_M_EW, LAT + 0.001)
    stretch = skipped_stretch(ON_17TH, start, rejoin)
    assert stretch is not None
    assert stretch == approx_line([[LON, LAT - 0.001], [LON, LAT], [LON, LAT + 0.001]])


def test_stretch_is_lon_lat():
    stretch = skipped_stretch(ON_17TH, (LON, LAT - 0.001), (LON, LAT + 0.001))
    assert stretch is not None
    assert stretch[0][0] == pytest.approx(-75.1716)
    assert stretch[0][1] == pytest.approx(39.9375)


def test_rejoin_before_start_is_none():
    """The other direction's points, or a loop measured the wrong way."""
    assert skipped_stretch(ON_17TH, (LON, LAT + 0.001), (LON, LAT - 0.001)) is None


def test_same_place_is_none():
    assert skipped_stretch(ON_17TH, (LON, LAT), (LON, LAT)) is None


@pytest.mark.parametrize(
    ("start_east_m", "rejoin_east_m", "placed"),
    [
        (490, 0, True),  # the start may be far off (ROUTE_RADIUS_M = 500)
        (510, 0, False),
        (0, 28, True),  # the rejoin must be on it (REJOIN_RADIUS_M = 30)
        (0, 32, False),
    ],
)
def test_points_too_far_from_the_line(start_east_m, rejoin_east_m, placed):
    start = (LON + start_east_m * DEG_PER_M_EW, LAT - 0.001)
    rejoin = (LON + rejoin_east_m * DEG_PER_M_EW, LAT + 0.001)
    assert (skipped_stretch(ON_17TH, start, rejoin) is not None) is placed


# A U: north 1 km up one street, 50 m east, back south 1 km on the next.
U_TURN = [
    [LON, LAT],
    [LON, LAT + 1000 * DEG_PER_M_NS],
    [LON + 50 * DEG_PER_M_EW, LAT + 1000 * DEG_PER_M_NS],
    [LON + 50 * DEG_PER_M_EW, LAT],
]


def test_stretch_far_longer_than_its_ends_apart_is_none():
    """Ends 50 m apart, ~1.9 km along the shape: doubt."""
    assert MAX_STRETCH_RATIO == 3.0
    start = (LON, LAT + 50 * DEG_PER_M_NS)
    rejoin = (LON + 50 * DEG_PER_M_EW, LAT + 50 * DEG_PER_M_NS)
    assert skipped_stretch(U_TURN, start, rejoin) is None


def test_stretch_within_the_ratio_is_kept():
    """Up and across the top: ~500 m + 50 m for ends ~502 m apart."""
    start = (LON, LAT + 500 * DEG_PER_M_NS)
    rejoin = (LON + 50 * DEG_PER_M_EW, LAT + 1000 * DEG_PER_M_NS)
    assert skipped_stretch(U_TURN, start, rejoin) is not None


def hairpin(depth_m: float) -> list[list[float]]:
    """North ``depth_m`` up one side, 5 m east, back south: legs 5 m apart."""
    top = LAT + depth_m * DEG_PER_M_NS
    east = LON + 5 * DEG_PER_M_EW
    return [[LON, LAT], [LON, top], [east, top], [east, LAT]]


@pytest.mark.parametrize(("depth_m", "kept"), [(40, True), (60, False)])
def test_slack_lets_a_short_hairpin_through(depth_m, kept):
    """Ends 5 m apart: the ratio alone allows 15 m, the slack 100 m more.

    40 m deep is an 85 m stretch (kept: under 115 m; it would fail with
    100 *feet* of slack); 60 m deep is 125 m (doubt).
    """
    assert STRETCH_SLACK_M == 100.0
    line = hairpin(depth_m)
    start = (LON, LAT + 0.0000001)
    rejoin = (LON + 5 * DEG_PER_M_EW, LAT + 0.0000001)
    assert (skipped_stretch(line, start, rejoin) is not None) is kept


def test_a_line_needs_two_points():
    with pytest.raises(ValueError, match="at least 2 points, got 1"):
        skipped_stretch([[LON, LAT]], (LON, LAT), (LON, LAT))
