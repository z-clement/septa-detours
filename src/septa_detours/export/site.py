"""Build the data contract's files (``export/contract.py``) from GTFS + detours.

Pure functions: no file I/O (that's ``write.py``).
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Final, NamedTuple

import polars as pl

from septa_detours.export.contract import (
    SCHEMA_VERSION,
    Bounds,
    DetourObject,
    DirectionEntry,
    HoursObject,
    Mode,
    RouteDetail,
    RouteEntry,
    StartPointObject,
    Status,
)
from septa_detours.export.geojson import (
    FeatureCollection,
    Position,
    Properties,
    _css_color,  # private; same stage
    line_feature,
    point_feature,
)
from septa_detours.export.simplify import (
    covering_shapes,
    cut_along,
    distinct_pieces,
    round_line,
    simplify_line,
)
from septa_detours.gtfs.load import Feed
from septa_detours.model import DailyHours, Detour, StartPoint

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

CUT_DECIMALS: Final = 6
"""``round_line`` places for a skipped stretch cut from a drawn line
(``skipped_line``): ~0.1 m, so its cut ends stay on the line when zoomed
far in (at 5 places, 0.37 m off on route 64: a visible sliver)."""

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


class RouteShape(NamedTuple):
    """One piece of a route's lines in one direction, ready to draw.

    A piece is part (or all) of one covering shape: the part no earlier
    shape of its direction already draws (``distinct_pieces``), so each
    direction is drawn once (UI plan U5b). A shape used in both
    directions gives pieces in each.
    """

    shape_id: str
    """The shape the piece comes from."""
    direction_id: int | None
    trip_count: int
    """How many trips use that shape in this direction."""
    line: list[Position]
    """Simplified at ``DETAIL_TOLERANCE_M`` and rounded."""


def detour_object(detour: Detour, pieces: Sequence[RouteShape] = ()) -> DetourObject:
    """One detour as the page reads it (route detail and ``status.json``).

    ``route`` is the route's ``key`` when matched, else the alerts API's
    route ID (``bus_route_H``), so an unmatched detour still says where it
    was posted. ``direction_id`` is the matched shapes' direction when
    they all agree, else ``None`` (no shapes, mixed, or unknown).
    ``issues`` lists parse issues, then match issues. Times are ISO 8601
    with the UTC offset as parsed; anything unknown is ``None``.
    ``skipped`` is ``skipped_line``, ``path`` is ``path_line``.
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
        "rejoin_streets": rejoin_streets(detour),
        "skipped": skipped_line(detour, pieces),
        "path": path_line(detour),
        "hours": hours_object(notice.daily_hours),
        "route_steps": [
            {"turn": step.turn, "street": step.street} for step in notice.route_steps
        ],
        "shape_ids": [shape.shape_id for shape in shapes],
    }


def rejoin_streets(detour: Detour) -> list[str] | None:
    """The streets that name a detour's rejoin (``DetourObject``), or ``None``.

    From the message's steps and ``RouteMatch.rejoin_by``: a crossing is
    the last two streets', a walk follows the last street back. ``None``
    without a rejoin, or when the steps can't name it (none, or one for
    a crossing: not from real matching, which needs two).
    """
    match = detour.match
    steps = detour.notice.route_steps
    if match is None or match.rejoin_by is None or match.rejoin_point is None:
        return None
    if match.rejoin_by == "crossing":
        return None if len(steps) < 2 else [steps[-2].street, steps[-1].street]
    return None if not steps else [steps[-1].street]


def _point_object(point: StartPoint | None) -> StartPointObject | None:
    """A start or rejoin point as the page reads it."""
    if point is None:
        return None
    return {"lon": point.lon, "lat": point.lat, "node_id": point.node_id}


def skipped_line(
    detour: Detour, pieces: Sequence[RouteShape] = ()
) -> list[Position] | None:
    """A detour's skipped stretch for the page, or ``None`` without one.

    Cut from its route's drawn line (``pieces``, ``cut_along``) in the
    stretch's direction, so the page's fade lies exactly on it: the
    stretch from ``match`` comes from a GTFS shape simplified and rounded
    separately, a fraction of a metre off, which shows as a sliver of
    route beside the fade when zoomed far in. Rounded to ``CUT_DECIMALS``:
    its ends are cut points between the piece's points, and rounding them
    to ~1 m would tilt it off the line again. When no piece holds both
    ends, the stretch itself, simplified at ``DETAIL_TOLERANCE_M`` and
    rounded to ``COORDINATE_DECIMALS``. Shared by the detour object
    and ``skipped.geojson``.
    """
    if detour.match is None or detour.match.skipped is None:
        return None
    stretch = detour.match.skipped
    line = simplify_line(stretch.line, DETAIL_TOLERANCE_M)
    # The detour's direction: its affected shapes share one (match picks
    # them by direction).
    directions = {shape.direction_id for shape in detour.match.shapes}
    drawn = [piece.line for piece in pieces if piece.direction_id in directions]
    cut = cut_along(drawn, line[0], line[-1])
    if cut is None:
        return round_line(line, COORDINATE_DECIMALS)
    return round_line(cut, CUT_DECIMALS)


def path_line(detour: Detour) -> list[Position] | None:
    """A detour's path for the page, or ``None`` without one.

    Simplified and rounded as ``skipped_line``. Shared by the detour
    object and ``paths.geojson``.
    """
    if detour.match is None or detour.match.path is None:
        return None
    line = simplify_line(detour.match.path, DETAIL_TOLERANCE_M)
    return round_line(line, COORDINATE_DECIMALS)


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
    detour_objects = [detour_object(detour, shapes) for detour in detours]
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
    """Prepare every route's lines: each direction drawn once, in pieces.

    Args:
        trips: Output of ``load.load_trips``. Trips without a ``shape_id``
            have nothing to draw and are skipped.
        coordinates: Output of ``shapes.shape_coordinates`` (raw lines).

    Returns:
        Route ``key`` -> its ``RouteShape`` pieces. Per direction: the
        shapes its trips use, simplified at ``DETAIL_TOLERANCE_M``; their
        covering set (``covering_shapes``, longest first: short-turns and
        stitched shapes add nothing); then ``distinct_pieces`` of those,
        so shapes sharing a street (a trunk, or copies digitized a metre
        apart) draw it once; each piece simplified again at
        ``DETAIL_TOLERANCE_M`` (dropping points the cut added on a
        straight stretch) and rounded to
        ``COORDINATE_DECIMALS``.
        Order: by ``direction_id`` (missing last), then piece order.
        Routes without shaped trips are absent.

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
    for (key, direction_id), members in sorted(
        groups.items(),
        key=lambda item: (item[0][0], item[0][1] is None, item[0][1] or 0),
    ):
        lines = {
            shape_id: simplified[(feed, shape_id)] for feed, shape_id, _ in members
        }
        trip_counts = {shape_id: trip_count for _, shape_id, trip_count in members}
        covering = covering_shapes(lines, COVERING_TOLERANCE_M)
        pieces = distinct_pieces([lines[shape_id] for shape_id in covering])
        shapes.setdefault(key, []).extend(
            RouteShape(
                shape_id=covering[index],
                direction_id=direction_id,
                trip_count=trip_counts[covering[index]],
                line=round_line(
                    simplify_line(piece, DETAIL_TOLERANCE_M), COORDINATE_DECIMALS
                ),
            )
            for index, piece in pieces
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
) -> FeatureCollection:
    """Build ``network.geojson``: the overview's lines for every route.

    Args:
        catalog: Output of ``route_catalog`` (order, ``mode``, ``color``).
        shapes: Output of ``route_shapes`` (each direction once, in pieces).

    Returns:
        One LineString per piece, properties ``NETWORK_PROPERTIES``. Each
        piece is simplified again at ``OVERVIEW_TOLERANCE_M`` (from the
        2 m lines: the two simplifications can add up to ~7 m, small next
        to ``COVERING_TOLERANCE_M``) and rounded to ``COORDINATE_DECIMALS``.
        Order: ``catalog`` order, then each route's ``route_shapes`` order.

    Raises:
        ValueError: ``shapes`` has a route that isn't in ``catalog``.
    """
    unknown = sorted(set(shapes) - {entry["key"] for entry in catalog})
    if unknown:
        raise ValueError(f"shapes for routes not in the catalog: {unknown}")
    features = []
    for entry in catalog:
        for shape in shapes.get(entry["key"], ()):
            line = round_line(
                simplify_line(shape.line, OVERVIEW_TOLERANCE_M), COORDINATE_DECIMALS
            )
            properties = {
                "key": entry["key"],
                "direction_id": shape.direction_id,
                "mode": entry["mode"],
                "color": entry["color"],
            }
            features.append(line_feature(line, properties))
    return {"type": "FeatureCollection", "features": features}


def starts_collection(
    catalog: Sequence[RouteEntry], detours: Sequence[Detour]
) -> FeatureCollection:
    """Build ``starts.geojson``: one dot per placed detour, all routes.

    Args:
        catalog: Output of ``route_catalog`` (each dot's ``color``).
        detours: The snapshot's detours; only placed ones (a matched route
            and a ``start_point``) get a dot.

    Returns:
        One Point per placed detour at its exact start node, in snapshot
        order, properties ``START_PROPERTIES``.

    Raises:
        ValueError: A placed detour's route isn't in ``catalog``.
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
        properties = _detour_properties(key, detour, colors[key])
        position = [match.start_point.lon, match.start_point.lat]
        features.append(point_feature(position, properties))
    return {"type": "FeatureCollection", "features": features}


def skipped_collection(
    catalog: Sequence[RouteEntry],
    detours: Sequence[Detour],
    shapes: Mapping[str, Sequence[RouteShape]] | None = None,
) -> FeatureCollection:
    """Build ``skipped.geojson``: each detour's skipped stretch, all routes.

    Args:
        catalog: Output of ``route_catalog`` (each line's ``color``).
        detours: The snapshot's detours; only those with a skipped stretch
            (``RouteMatch.skipped``) get a line.
        shapes: Output of ``route_shapes``: each stretch is cut from its
            route's drawn pieces (``skipped_line``); ``None``: the
            stretches as matched.

    Returns:
        One LineString per stretch (``skipped_line``), in snapshot order,
        properties ``SKIPPED_PROPERTIES``.

    Raises:
        ValueError: As ``starts_collection``.
    """
    pieces = shapes or {}

    def line_of(detour: Detour) -> list[Position] | None:
        match = detour.match
        key = None if match is None else route_key(match.feed, match.route_id)
        return skipped_line(detour, pieces.get(key, ()) if key else ())

    return _detour_lines(catalog, detours, line_of)


def paths_collection(
    catalog: Sequence[RouteEntry], detours: Sequence[Detour]
) -> FeatureCollection:
    """Build ``paths.geojson``: each detour's path, all routes.

    As ``skipped_collection``, with ``path_line`` (``RouteMatch.path``)
    and ``PATH_PROPERTIES``.
    """
    return _detour_lines(catalog, detours, path_line)


def _detour_lines(
    catalog: Sequence[RouteEntry],
    detours: Sequence[Detour],
    line_of: Callable[[Detour], list[Position] | None],
) -> FeatureCollection:
    """One LineString per detour that ``line_of`` gives a line for."""
    colors = {entry["key"]: entry["color"] for entry in catalog}
    features = []
    for detour in detours:
        line = line_of(detour)
        if line is None or detour.match is None:
            continue
        key = route_key(detour.match.feed, detour.match.route_id)
        if key not in colors:
            raise ValueError(
                f"detour {detour.notice.source_key} is on unknown route {key!r}"
            )
        properties = _detour_properties(key, detour, colors[key])
        features.append(line_feature(line, properties))
    return {"type": "FeatureCollection", "features": features}


def hours_object(hours: DailyHours | None) -> HoursObject | None:
    """Daily hours as the page reads them (``HoursObject``), or ``None``."""
    if hours is None:
        return None
    return {
        "days": list(hours.days),
        "start": hours.start.strftime("%H:%M"),
        "end": hours.end.strftime("%H:%M"),
    }


def _detour_properties(key: str, detour: Detour, color: str | None) -> Properties:
    """A detour feature's properties (``START_PROPERTIES``).

    Its route, its ``source_key`` (the page's feature id), the route's
    color, its overall ``start``/``end`` as in ``DetourObject``, and its
    daily hours flattened (``hours_*``): the page decides, with its own
    clock, which detours are in effect.
    """
    notice = detour.notice
    hours = hours_object(notice.daily_hours)
    return {
        "key": key,
        "source_key": notice.source_key,
        "color": color,
        "start": _iso(notice.start),
        "end": _iso(notice.end),
        "hours_days": None if hours is None else "".join(map(str, hours["days"])),
        "hours_start": None if hours is None else hours["start"],
        "hours_end": None if hours is None else hours["end"],
    }


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
