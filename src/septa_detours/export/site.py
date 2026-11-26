"""Build the data contract's files (``export/contract.py``) from GTFS + detours.

Pure functions: no file I/O (that's ``write.py``).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Final, NamedTuple

import polars as pl

from septa_detours.export.contract import (
    SCHEMA_VERSION,
    Bounds,
    DetourObject,
    DirectionEntry,
    Mode,
    RouteDetail,
    RouteEntry,
    StartPointObject,
    Status,
    Timing,
)
from septa_detours.export.geojson import (
    FeatureCollection,
    Position,
    Properties,
    _css_color,  # private; same stage
    line_feature,
    point_feature,
)
from septa_detours.export.simplify import covering_shapes, round_line, simplify_line
from septa_detours.gtfs.load import Feed
from septa_detours.model import Detour, StartPoint

MODE_ORDER: Final[tuple[Mode, ...]] = ("metro", "trolley", "trackless", "bus", "rail")
"""The sidebar's mode order (decided: the user's), fewest routes first."""

_MODES_BY_ROUTE_TYPE: Final[dict[int, Mode]] = {
    0: "trolley",
    1: "metro",
    2: "rail",
    3: "bus",
    11: "trackless",
}

_NUMBER = re.compile(r"[0-9]+")

_SAFE_ROUTE_ID = re.compile(r"[A-Za-z0-9_-]+")
"""Same rule as ``write.py``'s (a test checks they agree)."""

_SNAPSHOT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{6}Z\.json")
_SNAPSHOT_FORMAT = "%Y-%m-%dT%H%M%SZ.json"
"""How ``ingest`` names snapshots (a test checks they agree)."""

DETAIL_TOLERANCE_M: Final = 2.0
"""``simplify_line`` tolerance for a focused route's shapes (plan D2)."""

COVERING_TOLERANCE_M: Final = 20.0
"""``covering_shapes`` tolerance: which shapes the overview draws (D1)."""

COORDINATE_DECIMALS: Final = 5
"""``round_line`` places for every exported line: ~1 m (D2)."""

OVERVIEW_TOLERANCE_M: Final = 5.0
"""``simplify_line`` tolerance for ``network.geojson``'s lines (D2)."""


def route_mode(route_type: int) -> Mode:
    """Name a GTFS ``route_type`` the way the page shows it.

    Raises:
        ValueError: A type SEPTA doesn't use today: GTFS changed, so look
            before adding it (and decide where it goes in ``MODE_ORDER``).
    """
    try:
        return _MODES_BY_ROUTE_TYPE[route_type]
    except KeyError:
        raise ValueError(f"unknown route_type {route_type}") from None


def route_sort_key(mode: Mode, short_name: str) -> tuple[int, int, int, str, str]:
    """Sort key for the route list: by mode, then a natural name order.

    Modes go in ``MODE_ORDER``. Within a mode, all-digit names come first
    by value (``2`` before ``10`` before ``124``), then the rest
    alphabetically, ignoring case (``B1 OWL``, ``BLVDDIR``, ``K``...).
    Names equal ignoring case fall back to exact order, so the result
    never depends on input order.
    """
    if _NUMBER.fullmatch(short_name):
        return (MODE_ORDER.index(mode), 0, int(short_name), "", short_name)
    return (MODE_ORDER.index(mode), 1, 0, short_name.casefold(), short_name)


def route_key(feed: Feed, route_id: str) -> str:
    """The page's ID for a route: ``<feed>-<route_id>``, e.g. ``bus-21``.

    Used in file names (``routes/bus-21.json``), the URL and map filters.
    ``route_id`` alone isn't unique: IDs are only unique within a feed.

    Raises:
        ValueError: ``route_id`` has characters other than ASCII letters,
            digits, ``_`` and ``-`` (rejected, not cleaned: cleaning could
            give two routes the same key).
    """
    if not _SAFE_ROUTE_ID.fullmatch(route_id):
        raise ValueError(f"route_id {route_id!r} is not safe to use as a key")
    return f"{feed}-{route_id}"


def lines_bounds(lines: Iterable[Sequence[Sequence[float]]]) -> Bounds:
    """The smallest ``([west, south], [east, north])`` box around every point.

    Raises:
        ValueError: There are no points (a route without shapes has no
            bounds; the caller writes ``None``).
    """
    lons: list[float] = []
    lats: list[float] = []
    for line in lines:
        for point in line:
            lons.append(point[0])
            lats.append(point[1])
    if not lons:
        raise ValueError("no points to bound")
    return ([min(lons), min(lats)], [max(lons), max(lats)])


def route_catalog(
    routes: pl.DataFrame, bounds: Mapping[str, Bounds], detours: Sequence[Detour]
) -> list[RouteEntry]:
    """Build ``routes.json``: every route, in display order.

    Args:
        routes: Output of ``load.load_routes`` (both feeds: rail routes are
            listed even with no detours).
        bounds: Route ``key`` -> bounds of its shapes (``lines_bounds``),
            only for routes that have shapes.
        detours: The snapshot's detours. Unmatched ones (``match`` is
            ``None``) aren't counted here; they go in ``status.json``.

    Returns:
        One ``RouteEntry`` per route, sorted by ``route_sort_key`` (then
        ``key``, so equal names still have a fixed order). ``short_name``
        falls back to ``route_id`` when GTFS has none (blank counts as
        none); a blank ``long_name`` is ``None``. Routes without bounds
        get ``has_shapes: False`` and ``bounds: None``.

    Raises:
        ValueError: A ``(feed, route_id)`` appears twice in ``routes``
            (broken GTFS); a ``route_type`` is unknown (``route_mode``);
            or a ``bounds`` key or a matched detour's route isn't in
            ``routes`` (detours/shapes and GTFS disagree: loud, not
            silently dropped).
    """
    entries: dict[str, RouteEntry] = {}
    for row in routes.iter_rows(named=True):
        key = route_key(row["feed"], row["route_id"])
        if key in entries:
            raise ValueError(f"route {key!r} appears more than once in routes")
        route_bounds = bounds.get(key)
        entries[key] = {
            "key": key,
            "feed": row["feed"],
            "route_id": row["route_id"],
            "short_name": _blank_to_none(row["route_short_name"]) or row["route_id"],
            "long_name": _blank_to_none(row["route_long_name"]),
            "mode": route_mode(row["route_type"]),
            "color": _css_color(row["route_color"]),
            "text_color": _css_color(row["route_text_color"]),
            "has_shapes": route_bounds is not None,
            "bounds": None
            if route_bounds is None
            else (list(route_bounds[0]), list(route_bounds[1])),
            "detours": {"total": 0, "placed": 0, "windows": []},
        }

    unknown = sorted(set(bounds) - set(entries))
    if unknown:
        raise ValueError(f"bounds for routes not in routes: {unknown}")

    for detour in detours:
        if detour.match is None:
            continue
        key = route_key(detour.match.feed, detour.match.route_id)
        if key not in entries:
            raise ValueError(
                f"detour {detour.notice.source_key} is on unknown route {key!r}"
            )
        counts = entries[key]["detours"]
        counts["total"] += 1
        if detour.match.start_point is not None:
            counts["placed"] += 1
        counts["windows"].append((_iso(detour.notice.start), _iso(detour.notice.end)))

    return sorted(
        entries.values(),
        key=lambda entry: (
            route_sort_key(entry["mode"], entry["short_name"]),
            entry["key"],
        ),
    )


def detour_object(detour: Detour) -> DetourObject:
    """One detour as the page reads it (route detail and ``status.json``).

    ``route`` is the route's ``key`` when matched, else the alerts API's
    route ID (``bus_route_H``), so an unmatched detour still says where it
    was posted. ``direction_id`` is the matched shapes' direction when
    they all agree, else ``None`` (no shapes, mixed, or unknown).
    ``issues`` lists parse issues, then match issues. Times are ISO 8601
    with the UTC offset as parsed; anything unknown is ``None``.
    ``skipped`` is ``skipped_line``.
    """
    notice = detour.notice
    match = detour.match
    shapes = () if match is None else match.shapes
    direction_ids = {shape.direction_id for shape in shapes}
    return {
        "source_key": notice.source_key,
        "route": notice.source.route_id
        if match is None
        else route_key(match.feed, match.route_id),
        "status": notice.status,
        "direction": notice.direction,
        "direction_id": direction_ids.pop() if len(direction_ids) == 1 else None,
        "location_start": notice.location_start,
        "location_end": notice.location_end,
        "start": _iso(notice.start),
        "end": _iso(notice.end),
        "reason": notice.reason,
        "message": notice.source.message,
        "issues": [*notice.issues, *detour.issues],
        "start_point": _point_object(None if match is None else match.start_point),
        "rejoin_point": _point_object(None if match is None else match.rejoin_point),
        "skipped": skipped_line(detour),
        "shape_ids": [shape.shape_id for shape in shapes],
    }


def _point_object(point: StartPoint | None) -> StartPointObject | None:
    """A start or rejoin point as the page reads it."""
    if point is None:
        return None
    return {"lon": point.lon, "lat": point.lat, "node_id": point.node_id}


def skipped_line(detour: Detour) -> list[Position] | None:
    """A detour's skipped stretch for the page, or ``None`` without one.

    Simplified at ``DETAIL_TOLERANCE_M`` and rounded to
    ``COORDINATE_DECIMALS``, like a route detail's shapes, so it lies on
    the drawn route. Shared by the detour object and ``skipped.geojson``.
    """
    if detour.match is None or detour.match.skipped is None:
        return None
    line = simplify_line(detour.match.skipped.line, DETAIL_TOLERANCE_M)
    return round_line(line, COORDINATE_DECIMALS)


class RouteShape(NamedTuple):
    """One shape of a route in one direction, ready for its detail file.

    A shape used in both directions is two ``RouteShape``s.
    """

    shape_id: str
    direction_id: int | None
    trip_count: int
    """How many trips use this shape in this direction."""
    covering: bool
    """In this route-direction's covering set (``covering_shapes``)."""
    line: list[Position]
    """Already simplified and rounded (``simplify_line``, ``round_line``)."""


def route_detail(
    entry: RouteEntry,
    directions: Sequence[DirectionEntry],
    shapes: Sequence[RouteShape],
    detours: Sequence[Detour],
) -> RouteDetail:
    """Build ``routes/<key>.json``: what the page shows when a route is focused.

    Args:
        entry: The route's ``routes.json`` entry (its ``key`` and ``color``
            are used, so the two files can't disagree).
        directions: The route's directions, as they should appear.
        shapes: Every shape of the route, in drawing order.
        detours: The route's matched detours, in snapshot order.

    Returns:
        The detail, with one LineString per shape (properties
        ``SHAPE_PROPERTIES``) and one ``detour_object`` per detour.

    Raises:
        ValueError: A detour isn't matched to this route (a bug in the
            caller's grouping), or a shape has fewer than two points.
    """
    key = entry["key"]
    detour_objects = [detour_object(detour) for detour in detours]
    for detour, obj in zip(detours, detour_objects, strict=True):
        if obj["route"] != key:
            raise ValueError(
                f"detour {detour.notice.source_key} is on {obj['route']!r}, not {key!r}"
            )
    features = [
        line_feature(
            shape.line,
            {
                "shape_id": shape.shape_id,
                "direction_id": shape.direction_id,
                "trip_count": shape.trip_count,
                "covering": shape.covering,
                "color": entry["color"],
            },
        )
        for shape in shapes
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "key": key,
        "directions": [direction.copy() for direction in directions],
        "shapes": {"type": "FeatureCollection", "features": features},
        "detours": detour_objects,
    }


def route_shapes(
    trips: pl.DataFrame, coordinates: pl.DataFrame
) -> dict[str, list[RouteShape]]:
    """Prepare every route's shapes for its detail file.

    Args:
        trips: Output of ``load.load_trips``. Trips without a ``shape_id``
            have nothing to draw and are skipped.
        coordinates: Output of ``shapes.shape_coordinates`` (raw lines).

    Returns:
        Route ``key`` -> its shapes, one per ``(shape, direction)`` used by
        its trips. Each line is simplified at ``DETAIL_TOLERANCE_M`` and
        rounded to ``COORDINATE_DECIMALS``; ``covering`` comes from
        ``covering_shapes`` per direction, on the simplified lines. Order:
        by ``direction_id`` (missing last), covering first, most trips
        first, then ``shape_id``. Routes without shaped trips are absent.

    Raises:
        ValueError: A trip's shape has no coordinates (named, never
            silently dropped), or a ``route_id`` isn't safe (``route_key``).
    """
    counts = (
        trips.drop_nulls("shape_id")
        .group_by("feed", "route_id", "direction_id", "shape_id", maintain_order=True)
        .len("trip_count")
    )
    raw = {(feed, shape_id): line for feed, shape_id, line in coordinates.rows()}
    used = sorted(set(counts.select("feed", "shape_id").rows()))
    missing = [shape for shape in used if shape not in raw]
    if missing:
        raise ValueError(f"shapes used by trips have no coordinates: {missing}")
    simplified = {
        shape: simplify_line(raw[shape], DETAIL_TOLERANCE_M) for shape in used
    }

    groups: dict[tuple[str, int | None], list[tuple[str, str, int]]] = {}
    for row in counts.iter_rows(named=True):
        key = route_key(row["feed"], row["route_id"])
        groups.setdefault((key, row["direction_id"]), []).append(
            (row["feed"], row["shape_id"], row["trip_count"])
        )

    shapes: dict[str, list[RouteShape]] = {}
    for (key, direction_id), members in groups.items():
        lines = {
            shape_id: simplified[(feed, shape_id)] for feed, shape_id, _ in members
        }
        covering = set(covering_shapes(lines, COVERING_TOLERANCE_M))
        shapes.setdefault(key, []).extend(
            RouteShape(
                shape_id=shape_id,
                direction_id=direction_id,
                trip_count=trip_count,
                covering=shape_id in covering,
                line=round_line(lines[shape_id], COORDINATE_DECIMALS),
            )
            for _, shape_id, trip_count in members
        )
    for route in shapes.values():
        route.sort(
            key=lambda shape: (
                shape.direction_id is None,
                shape.direction_id or 0,
                not shape.covering,
                -shape.trip_count,
                shape.shape_id,
            )
        )
    return shapes


def route_directions(
    directions: pl.DataFrame, shapes: Mapping[str, Sequence[RouteShape]]
) -> dict[str, list[DirectionEntry]]:
    """List each route's directions for its detail file.

    Args:
        directions: Output of ``load.load_directions`` (SEPTA's extension).
        shapes: Output of ``route_shapes``.

    Returns:
        Route ``key`` -> its directions sorted by ``direction_id``: every
        ``directions.txt`` row, plus any direction its shapes use that the
        file lacks (``name``/``destination`` ``None``), so every drawn
        direction is listed. Names are stripped; blank -> ``None``. A route
        in either input gets an entry; shapes with no ``direction_id`` add
        nothing.

    Raises:
        ValueError: A row has no ``direction_id``, or a ``(route,
            direction_id)`` appears twice (broken data); or a ``route_id``
            isn't safe (``route_key``).
    """
    by_route: dict[str, dict[int, DirectionEntry]] = {}
    for row in directions.iter_rows(named=True):
        key = route_key(row["feed"], row["route_id"])
        direction_id = row["direction_id"]
        if direction_id is None:
            raise ValueError(f"directions row for {key!r} has no direction_id")
        route = by_route.setdefault(key, {})
        if direction_id in route:
            raise ValueError(
                f"direction {direction_id} of {key!r} appears more than once"
            )
        route[direction_id] = {
            "direction_id": direction_id,
            "name": _blank_to_none(row["direction"]),
            "destination": _blank_to_none(row["direction_destination"]),
        }
    for key, drawn in shapes.items():
        route = by_route.setdefault(key, {})
        for shape in drawn:
            if shape.direction_id is not None and shape.direction_id not in route:
                route[shape.direction_id] = {
                    "direction_id": shape.direction_id,
                    "name": None,
                    "destination": None,
                }
    return {key: [route[d] for d in sorted(route)] for key, route in by_route.items()}


def network_collection(
    catalog: Sequence[RouteEntry],
    shapes: Mapping[str, Sequence[RouteShape]],
    coordinates: pl.DataFrame,
) -> FeatureCollection:
    """Build ``network.geojson``: the overview's lines for every route.

    Args:
        catalog: Output of ``route_catalog`` (order, ``mode``, ``color``).
        shapes: Output of ``route_shapes``; only ``covering`` shapes are drawn.
        coordinates: Output of ``shapes.shape_coordinates`` (raw lines).

    Returns:
        One LineString per covering shape and direction, properties
        ``NETWORK_PROPERTIES``. Lines are simplified from the *raw* shape
        at ``OVERVIEW_TOLERANCE_M`` (not from the 2 m lines, so errors
        don't add up) and rounded to ``COORDINATE_DECIMALS``. Order:
        ``catalog`` order, then each route's ``route_shapes`` order.

    Raises:
        ValueError: ``shapes`` has a route that isn't in ``catalog``, or a
            covering shape has no coordinates.
    """
    unknown = sorted(set(shapes) - {entry["key"] for entry in catalog})
    if unknown:
        raise ValueError(f"shapes for routes not in the catalog: {unknown}")
    raw = {(feed, shape_id): line for feed, shape_id, line in coordinates.rows()}
    simplified: dict[tuple[str, str], list[Position]] = {}
    features = []
    for entry in catalog:
        for shape in shapes.get(entry["key"], ()):
            if not shape.covering:
                continue
            source = (entry["feed"], shape.shape_id)
            if source not in simplified:
                if source not in raw:
                    raise ValueError(f"shape {source} has no coordinates")
                simplified[source] = round_line(
                    simplify_line(raw[source], OVERVIEW_TOLERANCE_M),
                    COORDINATE_DECIMALS,
                )
            properties = {
                "key": entry["key"],
                "direction_id": shape.direction_id,
                "mode": entry["mode"],
                "color": entry["color"],
            }
            features.append(line_feature(simplified[source], properties))
    return {"type": "FeatureCollection", "features": features}


def detour_timing(
    start: datetime | None, end: datetime | None, now: datetime
) -> Timing:
    """Whether a detour is in effect at ``now``, by its overall start and end.

    ``active`` from ``start`` to ``end`` inclusive, ``upcoming`` before,
    ``ended`` after. ``unknown`` when a time is missing, or when ``end`` is
    before ``start`` (bad data: "upcoming" and "ended" could both be
    wrong). Recurring windows ("7am - 4pm Mon thru Fri") aren't parsed, so
    ``active`` means "inside the overall dates", not "running right now".
    The page has the same rule in JS; keep them in step.

    Raises:
        ValueError: ``now`` has no time zone (it couldn't be compared).
    """
    if now.tzinfo is None:
        raise ValueError("now must have a time zone")
    if start is None or end is None or end < start:
        return "unknown"
    if now < start:
        return "upcoming"
    if now > end:
        return "ended"
    return "active"


def starts_collection(
    catalog: Sequence[RouteEntry], detours: Sequence[Detour], now: datetime
) -> FeatureCollection:
    """Build ``starts.geojson``: one dot per placed detour, all routes.

    Args:
        catalog: Output of ``route_catalog`` (each dot's ``color``).
        detours: The snapshot's detours; only placed ones (a matched route
            and a ``start_point``) get a dot.
        now: When the export runs: ``timing`` is computed for this moment,
            as a first-paint default (the page recomputes it).

    Returns:
        One Point per placed detour at its exact start node, in snapshot
        order, properties ``START_PROPERTIES``.

    Raises:
        ValueError: A placed detour's route isn't in ``catalog``, or ``now``
            has no time zone (``detour_timing``).
    """
    colors = {entry["key"]: entry["color"] for entry in catalog}
    features = []
    for detour in detours:
        match = detour.match
        if match is None or match.start_point is None:
            continue
        key = route_key(match.feed, match.route_id)
        if key not in colors:
            raise ValueError(
                f"detour {detour.notice.source_key} is on unknown route {key!r}"
            )
        notice = detour.notice
        properties: Properties = {
            "key": key,
            "source_key": notice.source_key,
            "color": colors[key],
            "timing": detour_timing(notice.start, notice.end, now),
        }
        position = [match.start_point.lon, match.start_point.lat]
        features.append(point_feature(position, properties))
    return {"type": "FeatureCollection", "features": features}


def skipped_collection(
    catalog: Sequence[RouteEntry], detours: Sequence[Detour], now: datetime
) -> FeatureCollection:
    """Build ``skipped.geojson``: each detour's skipped stretch, all routes.

    Args:
        catalog: Output of ``route_catalog`` (each line's ``color``).
        detours: The snapshot's detours; only those with a skipped stretch
            (``RouteMatch.skipped``) get a line.
        now: As ``starts_collection``'s: the export-time ``timing``.

    Returns:
        One LineString per stretch (``skipped_line``), in snapshot order,
        properties ``SKIPPED_PROPERTIES``.

    Raises:
        ValueError: As ``starts_collection``.
    """
    colors = {entry["key"]: entry["color"] for entry in catalog}
    features = []
    for detour in detours:
        line = skipped_line(detour)
        if line is None or detour.match is None:
            continue
        key = route_key(detour.match.feed, detour.match.route_id)
        if key not in colors:
            raise ValueError(
                f"detour {detour.notice.source_key} is on unknown route {key!r}"
            )
        notice = detour.notice
        properties: Properties = {
            "key": key,
            "source_key": notice.source_key,
            "color": colors[key],
            "timing": detour_timing(notice.start, notice.end, now),
        }
        features.append(line_feature(line, properties))
    return {"type": "FeatureCollection", "features": features}


def status(
    detours: Sequence[Detour],
    snapshot: str,
    gtfs_versions: Mapping[Feed, str | None],
    generated_at: datetime,
) -> Status:
    """Build ``status.json``: provenance, totals, and unmatched detours.

    Unmatched detours are those whose route isn't in GTFS: the page lists
    them so none silently disappear.

    Args:
        detours: The snapshot's detours.
        snapshot: The alerts snapshot's file name, e.g.
            ``2026-11-25T121123Z.json``.
        gtfs_versions: Each feed's ``feed_version`` (``None`` if unknown).
        generated_at: When the export ran.

    Returns:
        ``generated_at`` as ISO 8601 UTC with ``Z``. ``snapshot_fetched_at``
        read from an ``ingest``-style name, else ``None`` (a hand-named
        snapshot, or one that isn't a real date). ``detours`` counts all,
        matched and placed; ``unmatched`` holds each unmatched detour's
        ``detour_object``, in snapshot order.

    Raises:
        ValueError: ``generated_at`` has no time zone.
    """
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must have a time zone")
    matches = [detour.match for detour in detours if detour.match is not None]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot": snapshot,
        "snapshot_fetched_at": _snapshot_fetched_at(snapshot),
        "gtfs": dict(gtfs_versions),
        "detours": {
            "total": len(detours),
            "matched": len(matches),
            "placed": sum(match.start_point is not None for match in matches),
        },
        "unmatched": [
            detour_object(detour) for detour in detours if detour.match is None
        ],
    }


def _snapshot_fetched_at(snapshot: str) -> str | None:
    """``2026-11-25T121123Z.json`` -> ``2026-11-25T12:11:23Z``; else ``None``."""
    if not _SNAPSHOT_NAME.fullmatch(snapshot):
        return None
    try:
        fetched_at = datetime.strptime(snapshot, _SNAPSHOT_FORMAT)  # noqa: DTZ007
    except ValueError:
        return None
    return fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _blank_to_none(text: str | None) -> str | None:
    """Strip ``text``; empty or missing -> ``None``."""
    if text is None:
        return None
    return text.strip() or None


def _iso(moment: datetime | None) -> str | None:
    """ISO 8601 with the offset as parsed (detour objects and windows)."""
    return None if moment is None else moment.isoformat()
