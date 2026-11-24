"""Build GeoJSON for a route's shapes.

Pure functions (no file I/O) so they can be tested with small hand-built
frames. Writing to disk lives in ``write.py``.

Pipeline for one route:
    1. ``join_route_lines(route_shape_ids(...), shape_coordinates(...))``
    2. ``route_properties(routes, ...)``
    3. ``route_feature_collection(lines from 1, props from 2)``, which
       calls ``line_feature`` once per row.

GeoJSON reminders:
    - Coordinates are ``[lon, lat]`` (``shape_coordinates`` already does this).
    - MapLibre styles from *feature* ``properties``; it ignores extra members
      on the FeatureCollection. So route-level metadata is copied onto every
      feature.
"""

import re
from typing import Literal, TypedDict

import polars as pl

from septa_detours.gtfs.load import Feed

type Position = list[float]
"""One ``[lon, lat]`` pair."""

type Properties = dict[str, str | int | None]
"""Feature properties. JSON-friendly scalars only."""


class LineString(TypedDict):
    """GeoJSON LineString geometry."""

    type: Literal["LineString"]
    coordinates: list[Position]


class Feature(TypedDict):
    """GeoJSON Feature with a LineString geometry."""

    type: Literal["Feature"]
    geometry: LineString
    properties: Properties


class FeatureCollection(TypedDict):
    """GeoJSON FeatureCollection."""

    type: Literal["FeatureCollection"]
    features: list[Feature]


def join_route_lines(
    route_shapes: pl.DataFrame, coordinates: pl.DataFrame
) -> pl.DataFrame:
    """Attach coordinate lists to a route's ``(shape, direction)`` rows.

    Args:
        route_shapes: Output of ``routes.route_shape_ids`` (``feed``,
            ``shape_id``, ``direction_id``).
        coordinates: Output of ``shapes.shape_coordinates`` (``feed``,
            ``shape_id``, ``coordinates``). May cover many routes; only the
            matching shapes are kept.

    Returns:
        A frame with ``feed``, ``shape_id``, ``direction_id``, and
        ``coordinates``, one row per ``route_shapes`` row, in
        ``route_shapes`` order.

    Raises:
        ValueError: If a ``shape_id`` in ``route_shapes`` has no coordinates.
            A silent inner-join drop would draw an incomplete route that
            looks complete.
        polars.exceptions.ComputeError: If ``coordinates`` has more than one
            row for a ``(feed, shape_id)``. ``shape_coordinates`` never
            produces that; it would mean duplicated features.

    Edge cases:
        - Join on ``["feed", "shape_id"]``, never ``shape_id`` alone.
        - A shape used in both directions appears twice (same geometry,
          different ``direction_id``); keep both rows.
        - Empty ``route_shapes`` gives an empty frame with the same columns.
        - A null ``shape_id`` never matches (polars joins don't treat nulls
          as equal), so it is reported as missing.
    """
    key = ["feed", "shape_id"]

    missing = route_shapes.join(coordinates, on=key, how="anti").select(key)
    if not missing.is_empty():
        missing_ids = missing.unique(maintain_order=True).rows()
        raise ValueError(f"No coordinates for (feed, shape_id): {missing_ids}")

    return route_shapes.join(
        coordinates.select(*key, "coordinates"),
        on=key,
        how="left",
        validate="m:1",
        maintain_order="left",
    ).select(*key, "direction_id", "coordinates")


def route_properties(routes: pl.DataFrame, feed: Feed, route_id: str) -> Properties:
    """Return the route-level properties shared by every feature of a route.

    Args:
        routes: Output of ``load.load_routes``.
        feed: The route's feed.
        route_id: The GTFS ``route_id``.

    Returns:
        A dict with ``feed``, ``route_id``, ``route_short_name``,
        ``route_long_name``, ``route_type``, ``route_color``, and
        ``route_text_color``.

    Raises:
        ValueError: If no route matches ``(feed, route_id)`` (this is the
            place to tell "unknown route" apart from "route with no shapes"),
            or if more than one does (GTFS requires ``route_id`` to be unique
            within a feed, so that means the data is broken).

    Edge cases:
        - Colors are converted to CSS form (see ``_css_color``).
        - ``route_color`` is optional; null stays null (let the frontend
          pick a fallback) rather than guessing a color here.
    """
    matches = routes.filter(pl.col("feed") == feed, pl.col("route_id") == route_id)
    if matches.height != 1:
        raise ValueError(
            f"Expected 1 route for ({feed!r}, {route_id!r}), found {matches.height}."
        )
    row = matches.row(0, named=True)
    return {
        "feed": row["feed"],
        "route_id": row["route_id"],
        "route_short_name": row["route_short_name"],
        "route_long_name": row["route_long_name"],
        "route_type": row["route_type"],
        "route_color": _css_color(row["route_color"]),
        "route_text_color": _css_color(row["route_text_color"]),
    }


_GTFS_COLOR = re.compile(r"[0-9A-Fa-f]{6}")


def _css_color(gtfs_color: str | None) -> str | None:
    """Turn a GTFS color (``"EF3340"``) into a CSS one (``"#EF3340"``).

    Null or malformed input gives ``None``: a missing color is better than
    a wrong one, and the frontend has a fallback.
    """
    if gtfs_color is None or not _GTFS_COLOR.fullmatch(gtfs_color):
        return None
    return f"#{gtfs_color}"


def line_feature(coordinates: list[Position], properties: Properties) -> Feature:
    """Wrap one coordinate list as a LineString Feature.

    Args:
        coordinates: ``[lon, lat]`` pairs in drawing order. The outer list
            is shallow-copied.
        properties: Shallow-copied onto the feature, so features never
            share (and later mutations never leak between) property dicts.

    Raises:
        ValueError: If there are fewer than two positions; a valid
            LineString needs at least two. The message includes
            ``properties`` so the bad shape can be identified.
    """
    if len(coordinates) < 2:
        raise ValueError(f"Received {len(coordinates)} pairs for feature: {properties}")
    geometry = LineString(type="LineString", coordinates=coordinates.copy())
    return Feature(type="Feature", geometry=geometry, properties=properties.copy())


def route_feature_collection(
    lines: pl.DataFrame, route_props: Properties
) -> FeatureCollection:
    """Build a FeatureCollection with one LineString Feature per row.

    Args:
        lines: Output of ``join_route_lines``.
        route_props: Output of ``route_properties``, merged into each
            feature's properties alongside ``shape_id`` and ``direction_id``.

    Returns:
        A FeatureCollection, features in ``lines`` row order. Empty ``lines``
        gives a valid, empty FeatureCollection (the caller decides if that
        is an error).

    Edge cases:
        - ``direction_id`` may be null; keep it as JSON ``null``.
        - Two features can share identical geometry (one per direction);
          the frontend should filter/style by ``direction_id``.
        - Per-row ``shape_id`` / ``direction_id`` win over same-named keys
          in ``route_props``.
    """
    features = [
        line_feature(
            row["coordinates"],
            {
                **route_props,
                "shape_id": row["shape_id"],
                "direction_id": row["direction_id"],
            },
        )
        for row in lines.iter_rows(named=True)
    ]
    return FeatureCollection(type="FeatureCollection", features=features)
