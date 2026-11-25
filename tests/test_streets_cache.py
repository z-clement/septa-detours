"""Tests for ``septa_detours.streets.cache``."""

import math

import polars as pl
import pytest

from septa_detours.streets.cache import (
    DEFAULT_MARGIN_M,
    combine_street_ways,
    service_bbox,
)
from septa_detours.streets.load import STREET_WAYS_SCHEMA

# Real-looking Philly [lon, lat] points.
A = [-75.1679, 39.9396]
B = [-75.1677, 39.9386]
C = [-75.1675, 39.9376]

BROAD = (101, "South Broad Street", "primary", [1, 2], [A, B])
WASHINGTON = (102, "Washington Avenue", "secondary", [2, 3], [B, C])
STATION = (107, "Station Drive", "service", [3, 1], [C, A])
TURNPIKE = (110, "Pennsylvania Turnpike", "motorway", [1, 3], [A, C])


def ways(*rows: tuple) -> pl.DataFrame:
    """A frame shaped like ``read_street_ways`` output."""
    return pl.DataFrame(list(rows), schema=STREET_WAYS_SCHEMA, orient="row")


def test_disjoint_frames_stack_in_order():
    combined = combine_street_ways([ways(BROAD, WASHINGTON), ways(STATION)])
    assert combined.rows() == [BROAD, WASHINGTON, STATION]
    assert combined.schema == STREET_WAYS_SCHEMA


def test_frame_order_decides_row_order():
    combined = combine_street_ways([ways(STATION), ways(BROAD, WASHINGTON)])
    assert combined.rows() == [STATION, BROAD, WASHINGTON]


def test_identical_way_in_two_frames_kept_once_at_first_position():
    """A border road: same way, same content, in PA and in DE."""
    combined = combine_street_ways(
        [ways(BROAD, TURNPIKE, WASHINGTON), ways(STATION, TURNPIKE)]
    )
    assert combined.rows() == [BROAD, TURNPIKE, WASHINGTON, STATION]


def test_identical_way_in_three_frames_kept_once():
    combined = combine_street_ways(
        [ways(TURNPIKE), ways(BROAD, TURNPIKE), ways(TURNPIKE, STATION)]
    )
    assert combined.rows() == [TURNPIKE, BROAD, STATION]


def test_single_frame_unchanged():
    assert combine_street_ways([ways(BROAD, WASHINGTON)]).rows() == [BROAD, WASHINGTON]


def test_empty_frames_give_empty_typed_frame():
    combined = combine_street_ways([ways(), ways()])
    assert combined.is_empty()
    assert combined.schema == STREET_WAYS_SCHEMA


def test_empty_frame_among_others_is_harmless():
    assert combine_street_ways([ways(), ways(BROAD), ways()]).rows() == [BROAD]


def test_no_frames_is_a_caller_bug():
    with pytest.raises(ValueError, match="empty"):
        combine_street_ways([])


@pytest.mark.parametrize(
    "edited",
    [
        (110, "Pennsylvania Tpke", "motorway", [1, 3], [A, C]),  # renamed
        (110, "Pennsylvania Turnpike", "trunk", [1, 3], [A, C]),  # reclassified
        (110, "Pennsylvania Turnpike", "motorway", [1, 2, 3], [A, B, C]),  # node added
        (110, "Pennsylvania Turnpike", "motorway", [1, 3], [A, [-75.1675, 39.9377]]),
    ],
    ids=["name", "highway", "nodes", "moved-node"],
)
def test_same_way_id_with_different_content_raises(edited):
    with pytest.raises(
        ValueError, match=r"^1 OSM ways differ between extracts \(way 110\)"
    ):
        combine_street_ways([ways(BROAD, TURNPIKE), ways(edited, STATION)])


def test_conflict_within_one_frame_also_raises():
    edited = (101, "Broad Street", *BROAD[2:])
    with pytest.raises(ValueError, match=r"\(way 101\)"):
        combine_street_ways([ways(BROAD, edited)])


def test_conflict_message_lists_five_ids_then_counts_the_rest():
    first = ways(*[(i, "Old Name", "residential", [1, 2], [A, B]) for i in range(1, 8)])
    second = ways(
        *[(i, "New Name", "residential", [1, 2], [A, B]) for i in range(1, 8)]
    )
    with pytest.raises(ValueError, match="re-fetch") as excinfo:
        combine_street_ways([first, second])
    assert str(excinfo.value).startswith(
        "7 OSM ways differ between extracts (way 1, 2, 3, 4, 5 and 2 more)"
    )


def test_conflict_message_with_exactly_five_ids_has_no_more():
    first = ways(*[(i, "Old Name", "residential", [1, 2], [A, B]) for i in range(1, 6)])
    second = ways(
        *[(i, "New Name", "residential", [1, 2], [A, B]) for i in range(1, 6)]
    )
    with pytest.raises(ValueError, match=r"\(way 1, 2, 3, 4, 5\);"):
        combine_street_ways([first, second])


# --- service_bbox --------------------------------------------------------------

# Real extreme stops (2026-11-25 feeds): the box's four edges.
WESTMOST = (-75.834693, 40.0)  # lon of the westernmost stop (rail, Parkesburg area)
EASTMOST = (-74.754202, 40.219322)  # Trenton Transit Center
SOUTHMOST = (-75.447687, 39.803811)  # Claymont Transit Center
NORTHMOST = (-75.3, 40.334014)

STOPS_SCHEMA = {"stop_lat": pl.Float64, "stop_lon": pl.Float64}


def stops(*points: tuple[float | None, float | None]) -> pl.DataFrame:
    """A stops-like frame from (lon, lat) points; extra columns are ignored."""
    rows = [(lat, lon) for lon, lat in points]
    return pl.DataFrame(rows, schema=STOPS_SCHEMA, orient="row").with_columns(
        stop_name=pl.lit("A & B"), feed=pl.lit("bus")
    )


# WGS84 ellipsoid (the datum of GPS, GTFS and OSM coordinates).
WGS84_A = 6_378_137.0  # equatorial radius, m
WGS84_E2 = 0.006_694_379_990_14  # first eccentricity squared


def parallel_m(lon1: float, lon2: float, lat: float) -> float:
    """Length in metres along the parallel at ``lat`` between two longitudes.

    Exact on the WGS84 ellipsoid; deliberately a different formula from the
    code under test (which uses a conservative spherical shortcut).
    """
    phi = math.radians(lat)
    radius = WGS84_A * math.cos(phi) / math.sqrt(1 - WGS84_E2 * math.sin(phi) ** 2)
    return radius * math.radians(abs(lon2 - lon1))


def meridian_m(lat1: float, lat2: float) -> float:
    """Length in metres along a meridian, using the WGS84 radius of curvature
    at the midpoint (accurate to well under a millimetre over 10 km)."""
    phi = math.radians((lat1 + lat2) / 2)
    radius = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * math.sin(phi) ** 2) ** 1.5
    return radius * math.radians(abs(lat2 - lat1))


SEPTA_STOPS = stops(WESTMOST, EASTMOST, SOUTHMOST, NORTHMOST, (-75.16, 39.95))


def test_zero_margin_is_exact_extent_in_west_south_east_north_order():
    assert service_bbox(SEPTA_STOPS, 0) == (
        WESTMOST[0],
        SOUTHMOST[1],
        EASTMOST[0],
        NORTHMOST[1],
    )


def test_row_order_does_not_matter():
    shuffled = stops(NORTHMOST, (-75.16, 39.95), SOUTHMOST, EASTMOST, WESTMOST)
    assert service_bbox(shuffled) == service_bbox(SEPTA_STOPS)


def test_default_margin_is_2_km():
    assert DEFAULT_MARGIN_M == 2000.0
    assert service_bbox(SEPTA_STOPS) == service_bbox(SEPTA_STOPS, 2000.0)


@pytest.mark.parametrize("margin_m", [10.0, 2000.0, 10_000.0])
def test_lat_margin_is_at_least_margin_and_under_1_percent_over(margin_m):
    _, south, _, north = service_bbox(SEPTA_STOPS, margin_m)
    south_gap = meridian_m(south, SOUTHMOST[1])
    north_gap = meridian_m(NORTHMOST[1], north)
    for gap in (south_gap, north_gap):
        assert margin_m <= gap < margin_m * 1.01


@pytest.mark.parametrize("margin_m", [10.0, 2000.0, 10_000.0])
def test_lon_margin_is_at_least_margin_everywhere_in_the_box(margin_m):
    """Checked along the box's north edge (where a degree of longitude is
    shortest, so the margin is tightest) and its south edge (loosest)."""
    west, south, east, north = service_bbox(SEPTA_STOPS, margin_m)
    for lat in (north, south):
        west_gap = parallel_m(west, WESTMOST[0], lat)
        east_gap = parallel_m(EASTMOST[0], east, lat)
        for gap in (west_gap, east_gap):
            assert margin_m <= gap < margin_m * 1.02


def test_southern_hemisphere_uses_the_edge_furthest_from_the_equator():
    """Mirror image of Philly: the margin must still be at least margin_m."""
    mirrored = stops((-75.2, -40.0), (-75.1, -39.9))
    west, south, east, _ = service_bbox(mirrored, 2000.0)
    assert parallel_m(west, -75.2, south) >= 2000.0
    assert parallel_m(-75.1, east, south) >= 2000.0


def test_single_stop_gives_a_box_around_it():
    west, south, east, north = service_bbox(stops((-75.16, 39.95)), 2000.0)
    assert west < -75.16 < east
    assert south < 39.95 < north


def test_stops_without_coordinates_are_ignored():
    with_nulls = stops((None, None), WESTMOST, (None, None), EASTMOST, SOUTHMOST)
    without = stops(WESTMOST, EASTMOST, SOUTHMOST)
    assert service_bbox(with_nulls, 0) == service_bbox(without, 0)


def test_half_null_point_is_ignored():
    """A stop with lat but no lon can't be placed; it mustn't stretch the box."""
    assert service_bbox(stops((None, 41.0), (-75.16, 39.95)), 0) == (
        -75.16,
        39.95,
        -75.16,
        39.95,
    )


@pytest.mark.parametrize(
    "frame",
    [stops(), stops((None, None), (None, None))],
    ids=["empty", "all-null"],
)
def test_no_stops_with_coordinates_raises(frame):
    with pytest.raises(ValueError, match="no stops with coordinates"):
        service_bbox(frame)


@pytest.mark.parametrize("margin_m", [-1.0, -0.001, math.nan])
def test_bad_margin_raises(margin_m):
    with pytest.raises(ValueError, match="margin_m must be >= 0"):
        service_bbox(SEPTA_STOPS, margin_m)
