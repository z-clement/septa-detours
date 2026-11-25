"""Build GeoJSON for matched detours (pure; no file I/O).

Reads ``Detour``s only (``model.py``); never reaches into ``parse/`` or
``match/``. Feature types and the generic builders live in ``geojson.py``.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

import polars as pl

from septa_detours.export.geojson import (
    Feature,
    FeatureCollection,
    Properties,
    join_route_lines,
    line_feature,
    point_feature,
    route_properties,
)
from septa_detours.model import Detour

ISSUE_SEPARATOR = "; "


def _iso(moment: datetime | None) -> str | None:
    """ISO 8601 with the offset kept (``2026-11-25T15:00:00-05:00``)."""
    return None if moment is None else moment.isoformat()


def detour_properties(detour: Detour) -> Properties:
    """Flatten one detour's own fields into feature properties.

    Route-level properties (``route_id``, colors, ...) aren't included: the
    caller merges ``route_properties`` in, since it needs the GTFS routes
    table. Neither is ``node_id``, which only the start point has.

    Every value is a string or ``None`` (MapLibre turns nested values into
    JSON strings, so nothing nested goes in):

    - ``start`` / ``end``: ISO 8601 with the UTC offset as parsed.
    - ``issues``: parse issues, then match issues, joined with ``"; "``;
      ``None`` if there are none. For reading, not for parsing back: the
      detours JSON keeps them as a list.
    - ``message``: the API text verbatim.
    - ``status``: the notice's ``status`` property.
    - Anything the notice couldn't determine is ``None``, never ``""``.
    """
    notice = detour.notice
    issues = (*notice.issues, *detour.issues)
    return {
        "source_key": notice.source_key,
        "status": notice.status,
        "direction": notice.direction,
        "location_start": notice.location_start,
        "location_end": notice.location_end,
        "start": _iso(notice.start),
        "end": _iso(notice.end),
        "reason": notice.reason,
        "message": notice.source.message,
        "issues": ISSUE_SEPARATOR.join(issues) if issues else None,
    }


# ``(feed, route_id, shape_id, direction_id)``: one drawn line. GTFS allows a
# null ``direction_id``; it stays its own line (and JSON ``null``).
type _LineKey = tuple[str, str, str, int | None]


def detours_feature_collection(
    detours: Sequence[Detour], routes: pl.DataFrame, coordinates: pl.DataFrame
) -> FeatureCollection:
    """Build one FeatureCollection: detoured route lines, then start points.

    Lines: one LineString per distinct ``(feed, route_id, shape_id,
    direction_id)`` among the matched detours' ``shapes``, placed or not,
    in first-appearance order. Properties: ``route_properties`` plus
    ``shape_id``, ``direction_id`` and ``detour_count`` (how many detours
    list that shape).

    Points: one Point per detour with a ``start_point``, in detour order.
    Properties: ``route_properties``, then ``detour_properties``, then
    ``node_id``.

    Unmatched detours draw nothing. A matched detour with no shapes (no
    direction) can still have a point. Empty input gives an empty
    collection. The frontend tells lines from points by geometry type.

    Args:
        detours: E.g. ``model.read_detours`` output.
        routes: Output of ``load.load_routes`` for the detours' feeds.
        coordinates: Output of ``shapes.shape_coordinates``; may cover more
            shapes than needed.

    Raises:
        ValueError: A detour's route isn't in ``routes``, or one of its
            shapes has no coordinates: the detours and GTFS disagree
            (rebuild the detours from the same GTFS).
    """
    props_by_route: dict[tuple[str, str], Properties] = {}
    line_counts: Counter[_LineKey] = Counter()
    points: list[Feature] = []

    for detour in detours:
        match = detour.match
        if match is None:
            continue
        route_key = (match.feed, match.route_id)
        if route_key not in props_by_route:
            props_by_route[route_key] = route_properties(
                routes, match.feed, match.route_id
            )
        route_props = props_by_route[route_key]

        for shape in match.shapes:
            key = (match.feed, match.route_id, shape.shape_id, shape.direction_id)
            line_counts[key] += 1

        start = match.start_point
        if start is not None:
            properties = {
                **route_props,
                **detour_properties(detour),
                "node_id": start.node_id,
            }
            points.append(point_feature([start.lon, start.lat], properties))

    lines = _line_features(line_counts, props_by_route, coordinates)
    return FeatureCollection(type="FeatureCollection", features=[*lines, *points])


def _line_features(
    line_counts: Counter[_LineKey],
    props_by_route: dict[tuple[str, str], Properties],
    coordinates: pl.DataFrame,
) -> list[Feature]:
    """One LineString Feature per key, in the counter's insertion order."""
    keys = list(line_counts)
    wanted = pl.DataFrame(
        [(feed, shape_id, direction_id) for feed, _, shape_id, direction_id in keys],
        schema={"feed": pl.String, "shape_id": pl.String, "direction_id": pl.Int8},
        orient="row",
    )
    # Raises on a shape with no coordinates; keeps ``wanted``'s row order.
    joined = join_route_lines(wanted, coordinates)

    features = []
    for key, row in zip(keys, joined.iter_rows(named=True), strict=True):
        feed, route_id, shape_id, direction_id = key
        properties: Properties = {
            **props_by_route[(feed, route_id)],
            "shape_id": shape_id,
            "direction_id": direction_id,
            "detour_count": line_counts[key],
        }
        features.append(line_feature(row["coordinates"], properties))
    return features
