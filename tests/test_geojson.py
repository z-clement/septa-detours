"""Tests for ``export.geojson`` using small hand-built frames."""

import json
import re

import polars as pl
import pytest
from polars.exceptions import ComputeError

from septa_detours.export.geojson import (
    Properties,
    join_route_lines,
    line_feature,
    point_feature,
    route_feature_collection,
    route_properties,
)

# Must match ``routes.route_shape_ids`` output.
ROUTE_SHAPES_SCHEMA = {
    "feed": pl.String,
    "shape_id": pl.String,
    "direction_id": pl.Int8,
}

# Must match ``shapes.shape_coordinates`` output.
COORDINATES_SCHEMA = {
    "feed": pl.String,
    "shape_id": pl.String,
    "coordinates": pl.List(pl.List(pl.Float64)),
}

# Must match ``join_route_lines`` output.
LINES_SCHEMA = {
    "feed": pl.String,
    "shape_id": pl.String,
    "direction_id": pl.Int8,
    "coordinates": pl.List(pl.List(pl.Float64)),
}

# Must match what ``load.load_routes`` returns (column order and dtypes).
ROUTES_SCHEMA = {
    "route_id": pl.String,
    "route_short_name": pl.String,
    "route_long_name": pl.String,
    "route_type": pl.Int16,
    "route_color": pl.String,
    "route_text_color": pl.String,
    "feed": pl.String,
}

# Realistic Philly coordinates in [lon, lat] order (lon ~ -75, lat ~ 40),
# so a lat/lon swap can't go unnoticed. Each line is distinct.
LINE_A = [[-75.25878, 39.961991], [-75.2101, 39.9588], [-75.1652, 39.9526]]
LINE_B = [[-75.143139, 39.945269], [-75.1652, 39.9526], [-75.25878, 39.961991]]
LINE_C = [[-75.1803, 39.9496], [-75.1711, 39.9509]]
LINE_D = [[-75.1500, 39.9800], [-75.1400, 39.9900]]
RAIL_LINE = [[-75.2400, 39.8700], [-75.1820, 39.9566]]


def make_route_shapes(rows: list[tuple]) -> pl.DataFrame:
    """Build a ``route_shape_ids``-style frame.

    Rows are ``(shape_id, direction_id, feed)`` tuples.
    """
    full_rows = [
        (feed, shape_id, direction_id) for shape_id, direction_id, feed in rows
    ]
    return pl.DataFrame(full_rows, schema=ROUTE_SHAPES_SCHEMA, orient="row")


def make_coordinates(rows: list[tuple]) -> pl.DataFrame:
    """Build a ``shape_coordinates``-style frame from ``(shape_id, coords, feed)``."""
    full_rows = [(feed, shape_id, coords) for shape_id, coords, feed in rows]
    return pl.DataFrame(full_rows, schema=COORDINATES_SCHEMA, orient="row")


def make_lines(rows: list[tuple]) -> pl.DataFrame:
    """Build a ``join_route_lines``-style frame.

    Rows are ``(shape_id, direction_id, coords, feed)`` tuples.
    """
    full_rows = [
        (feed, shape_id, direction_id, coords)
        for shape_id, direction_id, coords, feed in rows
    ]
    return pl.DataFrame(full_rows, schema=LINES_SCHEMA, orient="row")


def make_routes(rows: list[tuple]) -> pl.DataFrame:
    """Build a routes frame from ``(route_id, route_color, feed)`` tuples.

    Names come from ``route_id``, ``route_type`` is 3 (bus), and
    ``route_text_color`` is ``"FFFFFF"``.
    """
    full_rows = [
        (route_id, route_id, f"Route {route_id} long name", 3, color, "FFFFFF", feed)
        for route_id, color, feed in rows
    ]
    return pl.DataFrame(full_rows, schema=ROUTES_SCHEMA, orient="row")


# --- join_route_lines ---------------------------------------------------------


def test_join_attaches_coordinates_to_each_row():
    """Each route row gets its shape's coordinates."""
    route_shapes = make_route_shapes([("317337", 0, "bus"), ("317338", 1, "bus")])
    coordinates = make_coordinates(
        [("317337", LINE_A, "bus"), ("317338", LINE_B, "bus")]
    )
    output = join_route_lines(route_shapes, coordinates)
    expected = [("bus", "317337", 0, LINE_A), ("bus", "317338", 1, LINE_B)]
    assert expected == output.rows()


def test_join_keeps_route_shapes_order():
    """Output follows ``route_shapes`` order, not ``coordinates`` order.

    Four shapes, with ``coordinates`` in a different order, so a join that
    reorders rows is very unlikely to pass by accident.
    """
    route_shapes = make_route_shapes(
        [("s3", 0, "bus"), ("s1", 1, "bus"), ("s4", 0, "bus"), ("s2", 1, "bus")]
    )
    coordinates = make_coordinates(
        [
            ("s1", LINE_A, "bus"),
            ("s2", LINE_B, "bus"),
            ("s3", LINE_C, "bus"),
            ("s4", LINE_D, "bus"),
        ]
    )
    output = join_route_lines(route_shapes, coordinates)
    assert output["shape_id"].to_list() == ["s3", "s1", "s4", "s2"]
    assert output["coordinates"].to_list() == [LINE_C, LINE_A, LINE_D, LINE_B]


def test_join_matches_on_feed_as_well_as_shape_id():
    """The same ``shape_id`` in the other feed is a different shape."""
    route_shapes = make_route_shapes([("001005", 0, "bus")])
    coordinates = make_coordinates(
        [("001005", RAIL_LINE, "rail"), ("001005", LINE_A, "bus")]
    )
    output = join_route_lines(route_shapes, coordinates)
    expected = [("bus", "001005", 0, LINE_A)]
    assert expected == output.rows()


def test_join_shape_in_both_directions_gives_two_rows():
    """One shape used in both directions keeps both rows, same geometry."""
    route_shapes = make_route_shapes([("317337", 0, "bus"), ("317337", 1, "bus")])
    coordinates = make_coordinates([("317337", LINE_A, "bus")])
    output = join_route_lines(route_shapes, coordinates)
    expected = [("bus", "317337", 0, LINE_A), ("bus", "317337", 1, LINE_A)]
    assert expected == output.rows()


def test_join_ignores_shapes_of_other_routes():
    """``coordinates`` covers every shape; only the route's shapes come back."""
    route_shapes = make_route_shapes([("317337", 0, "bus")])
    coordinates = make_coordinates(
        [
            ("317480", LINE_C, "bus"),
            ("317337", LINE_A, "bus"),
            ("317481", LINE_D, "bus"),
        ]
    )
    output = join_route_lines(route_shapes, coordinates)
    expected = [("bus", "317337", 0, LINE_A)]
    assert expected == output.rows()


def test_join_missing_shape_raises_naming_it():
    """A shape with no coordinates is an error, not a silently dropped line."""
    route_shapes = make_route_shapes([("317337", 0, "bus"), ("999999", 1, "bus")])
    coordinates = make_coordinates([("317337", LINE_A, "bus")])
    with pytest.raises(ValueError, match=re.escape("('bus', '999999')")):
        join_route_lines(route_shapes, coordinates)


def test_join_shape_only_in_other_feed_counts_as_missing():
    """Coordinates for the right ``shape_id`` in the wrong feed don't count."""
    route_shapes = make_route_shapes([("001005", 0, "bus")])
    coordinates = make_coordinates([("001005", RAIL_LINE, "rail")])
    with pytest.raises(ValueError, match=re.escape("('bus', '001005')")):
        join_route_lines(route_shapes, coordinates)


def test_join_null_shape_id_counts_as_missing():
    """A null ``shape_id`` never matches, so it is reported, not dropped."""
    route_shapes = make_route_shapes([("317337", 0, "bus"), (None, 1, "bus")])
    coordinates = make_coordinates([("317337", LINE_A, "bus")])
    with pytest.raises(ValueError, match=re.escape("('bus', None)")):
        join_route_lines(route_shapes, coordinates)


def test_join_duplicate_coordinates_raise():
    """Two coordinate rows for one shape would duplicate features."""
    route_shapes = make_route_shapes([("317337", 0, "bus")])
    coordinates = make_coordinates(
        [("317337", LINE_A, "bus"), ("317337", LINE_B, "bus")]
    )
    with pytest.raises(ComputeError):
        join_route_lines(route_shapes, coordinates)


def test_join_empty_route_shapes_gives_empty_frame_with_schema():
    """No shapes (unknown or shapeless route) is not an error here."""
    route_shapes = make_route_shapes([])
    coordinates = make_coordinates([("317337", LINE_A, "bus")])
    output = join_route_lines(route_shapes, coordinates)
    assert output.is_empty()
    assert output.schema == LINES_SCHEMA


def test_join_output_schema_drops_extra_columns():
    """Extra columns on either input don't leak into the output."""
    route_shapes = make_route_shapes([("317337", 0, "bus")]).with_columns(
        route_extra=pl.lit("x")
    )
    coordinates = make_coordinates([("317337", LINE_A, "bus")]).with_columns(
        coord_extra=pl.lit("y")
    )
    output = join_route_lines(route_shapes, coordinates)
    assert output.schema == LINES_SCHEMA


# --- route_properties ---------------------------------------------------------


def test_route_properties_returns_route_fields():
    """The whole dict, so a missing, extra, or renamed key fails."""
    routes = make_routes([("42", "1A1818", "bus"), ("21", "EF3340", "bus")])
    output = route_properties(routes, "bus", "21")
    expected = {
        "feed": "bus",
        "route_id": "21",
        "route_short_name": "21",
        "route_long_name": "Route 21 long name",
        "route_type": 3,
        "route_color": "#EF3340",
        "route_text_color": "#FFFFFF",
    }
    assert expected == output


def test_route_properties_unknown_route_raises():
    """No matching route is an error."""
    routes = make_routes([("21", "EF3340", "bus")])
    with pytest.raises(ValueError, match="found 0"):
        route_properties(routes, "bus", "no-such-route")


def test_route_properties_route_only_in_other_feed_raises():
    """A ``route_id`` that exists only in the other feed is not a match."""
    routes = make_routes([("21", "EF3340", "rail")])
    with pytest.raises(ValueError, match="found 0"):
        route_properties(routes, "bus", "21")


def test_route_properties_picks_requested_feed():
    """With the ``route_id`` in both feeds, the requested feed's row is used."""
    routes = make_routes([("21", "000000", "rail"), ("21", "EF3340", "bus")])
    output = route_properties(routes, "bus", "21")
    assert output["feed"] == "bus"
    assert output["route_color"] == "#EF3340"


def test_route_properties_duplicate_route_raises():
    """``route_id`` must be unique within a feed; two matches is broken data."""
    routes = make_routes([("21", "EF3340", "bus"), ("21", "1A1818", "bus")])
    with pytest.raises(ValueError, match="found 2"):
        route_properties(routes, "bus", "21")


def test_route_properties_matches_route_id_exactly():
    """``"21"`` does not match ``"021"`` or ``"210"``; IDs are not numbers."""
    routes = make_routes([("021", "000000", "bus"), ("210", "111111", "bus")])
    with pytest.raises(ValueError, match="found 0"):
        route_properties(routes, "bus", "21")


@pytest.mark.parametrize(
    ("gtfs_color", "expected"),
    [
        ("EF3340", "#EF3340"),
        ("ef3340", "#ef3340"),
        (None, None),
        ("F00", None),
        ("#EF3340", None),
        ("GGGGGG", None),
        ("EF33401", None),
        (" EF3340", None),
    ],
)
def test_route_properties_color_conversion(gtfs_color, expected):
    """Valid 6-digit hex gets a ``#``; null or malformed becomes ``None``."""
    routes = make_routes([("21", gtfs_color, "bus")]).with_columns(
        route_text_color=pl.lit(gtfs_color, dtype=pl.String)
    )
    output = route_properties(routes, "bus", "21")
    assert output["route_color"] == expected
    assert output["route_text_color"] == expected


# --- line_feature -------------------------------------------------------------


def test_line_feature_structure():
    """The whole Feature, so any wrong key or ``type`` value fails."""
    output = line_feature(LINE_A, {"shape_id": "317337", "direction_id": 0})
    expected = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": LINE_A},
        "properties": {"shape_id": "317337", "direction_id": 0},
    }
    assert expected == output


def test_line_feature_accepts_two_points():
    """Two positions is the minimum valid LineString."""
    output = line_feature(LINE_C, {})
    assert output["geometry"]["coordinates"] == LINE_C


@pytest.mark.parametrize("coordinates", [[], [[-75.1652, 39.9526]]])
def test_line_feature_too_few_points_raises_with_properties(coordinates):
    """Under two positions raises, and the message identifies the shape."""
    with pytest.raises(ValueError, match="317337"):
        line_feature(coordinates, {"shape_id": "317337"})


def test_line_feature_does_not_share_properties():
    """Mutating the caller's dict afterwards doesn't change the feature."""
    properties = {"shape_id": "317337"}
    output = line_feature(LINE_A, properties)
    properties["shape_id"] = "changed"
    assert output["properties"] == {"shape_id": "317337"}


def test_line_feature_does_not_share_coordinate_list():
    """Appending to the caller's list afterwards doesn't change the feature."""
    coordinates = [list(pair) for pair in LINE_A]
    output = line_feature(coordinates, {})
    coordinates.append([-75.0, 40.0])
    assert output["geometry"]["coordinates"] == LINE_A


# --- point_feature ------------------------------------------------------------

# Near 17th & Washington; lon ~ -75 so a lat/lon swap would show.
POINT = [-75.1716, 39.9385]


def test_point_feature_structure():
    """The whole Feature, so any wrong key or ``type`` value fails."""
    output = point_feature(POINT, {"source_key": "661b7024a25d2bbd", "node_id": 11})
    expected = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-75.1716, 39.9385]},
        "properties": {"source_key": "661b7024a25d2bbd", "node_id": 11},
    }
    assert expected == output


def test_point_feature_serializes_as_geojson():
    """Round-trips through JSON unchanged: plain dicts, lists and floats."""
    output = point_feature(POINT, {"status": None})
    assert json.loads(json.dumps(output)) == output


@pytest.mark.parametrize(
    "position",
    [[], [-75.1716], [-75.1716, 39.9385, 12.0]],
    ids=["empty", "one", "three"],
)
def test_point_feature_wrong_length_raises_with_properties(position):
    with pytest.raises(ValueError, match="661b7024a25d2bbd"):
        point_feature(position, {"source_key": "661b7024a25d2bbd"})


def test_point_feature_does_not_share_properties():
    properties: Properties = {"source_key": "661b7024a25d2bbd"}
    output = point_feature(POINT, properties)
    properties["source_key"] = "changed"
    assert output["properties"] == {"source_key": "661b7024a25d2bbd"}


def test_point_feature_does_not_share_position():
    position = list(POINT)
    output = point_feature(position, {})
    position[0] = 0.0
    assert output["geometry"]["coordinates"] == POINT


# --- route_feature_collection -------------------------------------------------

ROUTE_21_PROPS = {
    "feed": "bus",
    "route_id": "21",
    "route_color": "#EF3340",
}


def test_collection_structure():
    """The whole collection: one feature per row, route and row props merged."""
    lines = make_lines([("317337", 0, LINE_A, "bus"), ("317338", 1, LINE_B, "bus")])
    output = route_feature_collection(lines, ROUTE_21_PROPS)
    expected = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": LINE_A},
                "properties": {
                    "feed": "bus",
                    "route_id": "21",
                    "route_color": "#EF3340",
                    "shape_id": "317337",
                    "direction_id": 0,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": LINE_B},
                "properties": {
                    "feed": "bus",
                    "route_id": "21",
                    "route_color": "#EF3340",
                    "shape_id": "317338",
                    "direction_id": 1,
                },
            },
        ],
    }
    assert expected == output


def test_collection_follows_lines_order():
    """Features come out in ``lines`` row order."""
    lines = make_lines(
        [
            ("s3", 0, LINE_C, "bus"),
            ("s1", 1, LINE_A, "bus"),
            ("s4", 0, LINE_D, "bus"),
            ("s2", 1, LINE_B, "bus"),
        ]
    )
    output = route_feature_collection(lines, ROUTE_21_PROPS)
    shape_ids = [f["properties"]["shape_id"] for f in output["features"]]
    assert shape_ids == ["s3", "s1", "s4", "s2"]


def test_collection_row_values_win_over_route_props():
    """Per-row ``shape_id`` / ``direction_id`` override same-named route keys."""
    lines = make_lines([("317337", 1, LINE_A, "bus")])
    route_props = {**ROUTE_21_PROPS, "shape_id": "stale", "direction_id": 0}
    output = route_feature_collection(lines, route_props)
    properties = output["features"][0]["properties"]
    assert properties["shape_id"] == "317337"
    assert properties["direction_id"] == 1


def test_collection_null_direction_stays_null():
    """A null ``direction_id`` is kept as ``None`` (JSON ``null``), not dropped."""
    lines = make_lines([("317337", None, LINE_A, "bus")])
    output = route_feature_collection(lines, ROUTE_21_PROPS)
    properties = output["features"][0]["properties"]
    assert "direction_id" in properties
    assert properties["direction_id"] is None


def test_collection_features_do_not_share_properties():
    """Each feature owns its dict; editing one leaves the others alone."""
    lines = make_lines([("317337", 0, LINE_A, "bus"), ("317338", 1, LINE_B, "bus")])
    output = route_feature_collection(lines, ROUTE_21_PROPS)
    first, second = output["features"]
    first["properties"]["route_color"] = "#000000"
    assert second["properties"]["route_color"] == "#EF3340"


def test_collection_does_not_mutate_route_props():
    """The caller's ``route_props`` dict is left unchanged."""
    route_props = dict(ROUTE_21_PROPS)
    lines = make_lines([("317337", 0, LINE_A, "bus")])
    route_feature_collection(lines, route_props)
    assert route_props == ROUTE_21_PROPS


def test_collection_empty_lines_gives_empty_collection():
    """No lines is still a valid FeatureCollection; the caller decides."""
    output = route_feature_collection(make_lines([]), ROUTE_21_PROPS)
    assert output == {"type": "FeatureCollection", "features": []}


def test_collection_is_json_serializable():
    """Values are plain Python types, not polars objects, so ``json`` accepts them.

    ``allow_nan=False`` matches what ``write.py`` should use.
    """
    lines = make_lines([("317337", None, LINE_A, "bus")])
    output = route_feature_collection(lines, ROUTE_21_PROPS)
    assert json.loads(json.dumps(output, allow_nan=False)) == output
