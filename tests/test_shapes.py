"""Tests for ``gtfs.shapes.shape_coordinates`` using small hand-built frames."""

import polars as pl

from septa_detours.gtfs.shapes import shape_coordinates

# Must match what ``load.load_shapes`` returns. If the hand-built frames use
# different dtypes (e.g. Int64 instead of Int32), the tests check a frame
# that the real pipeline never produces.
SHAPES_SCHEMA = {
    "shape_id": pl.String,
    "shape_pt_lat": pl.Float64,
    "shape_pt_lon": pl.Float64,
    "shape_pt_sequence": pl.Int32,
    "feed": pl.String,
}


def make_shapes(rows: list[tuple]) -> pl.DataFrame:
    """Build a shapes frame from ``(shape_id, lat, lon, seq, feed)`` tuples.

    Lets each test show its input as a short readable list of points.
    """
    return pl.DataFrame(rows, schema=SHAPES_SCHEMA, orient="row")


def test_sorts_points_by_sequence_not_input_order():
    """Points stored out of order come back in ``shape_pt_sequence`` order."""
    shapes = make_shapes(
        [
            ("00101", 39.5, -74.3, 3, "bus"),
            ("00101", 38.5, -75.3, 1, "bus"),
            ("00101", 37.5, -75.3, 2, "bus"),
        ]
    )
    output = shape_coordinates(shapes)
    expected = [[[-75.3, 38.5], [-75.3, 37.5], [-74.3, 39.5]]]
    assert expected == output["coordinates"].to_list()


def test_sequence_gaps_are_ordered_not_indexed():
    """Sequences like 1, 2, 5 give three points in order, with no padding."""
    shapes = make_shapes(
        [
            ("00101", 39.5, -74.3, 1, "bus"),
            ("00101", 38.5, -75.3, 2, "bus"),
            ("00101", 37.5, -75.3, 5, "bus"),
        ]
    )
    output = shape_coordinates(shapes)
    expected = [[[-74.3, 39.5], [-75.3, 38.5], [-75.3, 37.5]]]
    assert expected == output["coordinates"].to_list()


def test_coordinates_are_lon_lat():
    """Each pair is ``[lon, lat]`` (GeoJSON), not GTFS's lat, lon order."""
    shapes = make_shapes(
        [
            ("00101", 39.5, -74.3, 1, "bus"),
        ]
    )
    output = shape_coordinates(shapes)
    expected = [-74.3, 39.5]
    assert expected == output["coordinates"].to_list()[0][0]


def test_same_shape_id_in_both_feeds_stays_separate():
    """One shape_id in both feeds gives two rows; points are not merged."""
    shapes = make_shapes(
        [
            ("00101", 39.5, -74.3, 1, "bus"),
            ("00101", 38.5, -75.3, 1, "rail"),
            ("00101", 37.5, -75.3, 2, "bus"),
        ]
    )
    output = shape_coordinates(shapes)
    expected = [
        ("bus", "00101", [[-74.3, 39.5], [-75.3, 37.5]]),
        ("rail", "00101", [[-75.3, 38.5]]),
    ]
    assert expected == output.rows()


def test_groups_in_first_appearance_order():
    """Output rows follow the order each ``(feed, shape_id)`` first appears."""
    shapes = make_shapes(
        [
            ("00102", 39.5, -74.3, 1, "bus"),
            ("00101", 38.5, -75.3, 1, "bus"),
            ("00101", 37.5, -75.3, 2, "bus"),
        ]
    )
    output = shape_coordinates(shapes)
    expected = ["00102", "00101"]
    assert expected == output["shape_id"].to_list()


def test_output_schema():
    """Columns are feed, shape_id, coordinates; coordinates is List(List(Float64))."""
    shapes = make_shapes(
        [
            ("00101", 39.5, -74.3, 1, "bus"),
            ("00101", 38.5, -75.3, 1, "rail"),
            ("00101", 37.5, -75.3, 2, "bus"),
        ]
    )
    output = shape_coordinates(shapes)
    expected = {
        "feed": pl.String,
        "shape_id": pl.String,
        "coordinates": pl.List(pl.List(pl.Float64)),
    }
    assert expected == output.schema
