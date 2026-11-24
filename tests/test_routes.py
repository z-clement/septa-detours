"""Tests for ``gtfs.routes.route_shape_ids`` using small hand-built frames."""

import polars as pl

from septa_detours.gtfs.routes import route_shape_ids

# Must match what ``load.load_trips`` returns (column order and dtypes).
TRIPS_SCHEMA = {
    "route_id": pl.String,
    "service_id": pl.String,
    "trip_id": pl.String,
    "trip_headsign": pl.String,
    "direction_id": pl.Int8,
    "shape_id": pl.String,
    "feed": pl.String,
}

OUTPUT_SCHEMA = {
    "feed": pl.String,
    "shape_id": pl.String,
    "direction_id": pl.Int8,
}


def make_trips(rows: list[tuple]) -> pl.DataFrame:
    """Build a trips frame from ``(route_id, direction_id, shape_id, feed)`` tuples.

    ``route_shape_ids`` ignores ``service_id``, ``trip_id``, and
    ``trip_headsign``, so they are filled in automatically (``trip_id`` is
    unique per row, as in real data).
    """
    full_rows = [
        (route_id, "WKDY", f"trip{i}", "Somewhere", direction_id, shape_id, feed)
        for i, (route_id, direction_id, shape_id, feed) in enumerate(rows)
    ]
    return pl.DataFrame(full_rows, schema=TRIPS_SCHEMA, orient="row")


def test_many_trips_collapse_to_distinct_shapes():
    """Repeated trips on the same shape and direction give one row each."""
    trips = make_trips(
        [
            ("21", 0, "317337", "bus"),
            ("21", 1, "317338", "bus"),
            ("21", 0, "317337", "bus"),
            ("21", 1, "317338", "bus"),
            ("21", 0, "317337", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    expected = [("bus", "317337", 0), ("bus", "317338", 1)]
    assert expected == output.rows()


def test_other_routes_are_excluded():
    """Only trips on the requested ``route_id`` contribute shapes."""
    trips = make_trips(
        [
            ("42", 0, "317480", "bus"),
            ("21", 0, "317337", "bus"),
            ("L1", 0, "317900", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    expected = [("bus", "317337", 0)]
    assert expected == output.rows()


def test_route_id_is_matched_exactly_as_a_string():
    """``"21"`` does not match ``"021"`` or ``"210"``; IDs are not numbers."""
    trips = make_trips(
        [
            ("021", 0, "000001", "bus"),
            ("210", 0, "000002", "bus"),
            ("21", 0, "000003", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    expected = [("bus", "000003", 0)]
    assert expected == output.rows()


def test_same_route_id_in_other_feed_is_excluded():
    """A ``route_id`` present in both feeds returns only the requested feed."""
    trips = make_trips(
        [
            ("21", 0, "317337", "rail"),
            ("21", 0, "317337", "bus"),
            ("21", 1, "001005", "rail"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    expected = [("bus", "317337", 0)]
    assert expected == output.rows()


def test_trips_without_shape_are_dropped():
    """A null ``shape_id`` has nothing to draw, so it gives no row."""
    trips = make_trips(
        [
            ("21", 0, None, "bus"),
            ("21", 1, "317338", "bus"),
            ("21", 1, None, "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    expected = [("bus", "317338", 1)]
    assert expected == output.rows()


def test_route_whose_trips_all_lack_shapes_is_empty():
    """A real route with no shapes gives an empty frame, like an unknown one."""
    trips = make_trips(
        [
            ("21", 0, None, "bus"),
            ("21", 1, None, "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    assert output.is_empty()
    assert output.schema == OUTPUT_SCHEMA


def test_shape_used_in_both_directions_gives_two_rows():
    """Direction matters for one-way detours, so each direction keeps its row."""
    trips = make_trips(
        [
            ("21", 0, "317337", "bus"),
            ("21", 1, "317337", "bus"),
            ("21", 0, "317337", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    expected = [("bus", "317337", 0), ("bus", "317337", 1)]
    assert expected == output.rows()


def test_null_direction_is_kept_as_its_own_row():
    """A null ``direction_id`` is not dropped and not merged with 0 or 1."""
    trips = make_trips(
        [
            ("21", 0, "317337", "bus"),
            ("21", None, "317337", "bus"),
            ("21", None, "317337", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    expected = [("bus", "317337", 0), ("bus", "317337", None)]
    assert expected == output.rows()


def test_rows_in_first_appearance_order():
    """Rows follow first appearance in ``trips``, not sorted order.

    Uses four shapes in a non-sorted order so that a sort, or a random
    order, is very unlikely to pass by accident.
    """
    trips = make_trips(
        [
            ("42", 0, "317483", "bus"),
            ("42", 1, "317485", "bus"),
            ("42", 0, "317480", "bus"),
            ("42", 0, "317483", "bus"),
            ("42", 1, "317484", "bus"),
            ("42", 0, "317480", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "42")
    expected = ["317483", "317485", "317480", "317484"]
    assert expected == output["shape_id"].to_list()


def test_shape_id_leading_zeros_are_preserved():
    """Rail-style ``shape_id``s like ``"001005"`` come back unchanged."""
    trips = make_trips(
        [
            ("AIR", 0, "001005", "rail"),
            ("AIR", 1, "538_406", "rail"),
        ]
    )
    output = route_shape_ids(trips, "rail", "AIR")
    expected = [("rail", "001005", 0), ("rail", "538_406", 1)]
    assert expected == output.rows()


def test_unknown_route_gives_empty_frame_with_schema():
    """An unknown ``route_id`` is not an error; it gives an empty, typed frame."""
    trips = make_trips(
        [
            ("21", 0, "317337", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "no-such-route")
    assert output.is_empty()
    assert output.schema == OUTPUT_SCHEMA


def test_output_schema():
    """Columns are feed, shape_id, direction_id, with the loader's dtypes."""
    trips = make_trips(
        [
            ("21", 0, "317337", "bus"),
        ]
    )
    output = route_shape_ids(trips, "bus", "21")
    assert output.schema == OUTPUT_SCHEMA
