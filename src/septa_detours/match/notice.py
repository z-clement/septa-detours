"""Turn ``DetourNotice`` objects into ``Detour`` objects by matching to GTFS."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import polars as pl

from septa_detours.gtfs.load import Feed
from septa_detours.gtfs.routes import route_shape_ids
from septa_detours.gtfs.shapes import shape_coordinates
from septa_detours.match.directions import find_direction_id
from septa_detours.match.place import find_rejoin_point, find_start_point
from septa_detours.match.routes import find_gtfs_route
from septa_detours.match.streets import street_key_table
from septa_detours.model import (
    AffectedShape,
    Detour,
    DetourNotice,
    Direction,
    RouteMatch,
)

type ShapeLines = Mapping[tuple[Feed, str], list[list[float]]]
"""``(feed, shape_id)`` -> the shape's ``[lon, lat]`` points, in order."""


@dataclass(frozen=True, kw_only=True)
class MatchReference:
    """Everything matching reads besides the notice; built once per run.

    Keyword-only, so five frames of the same type can't be passed in the
    wrong order. Build it with ``build_match_reference``, which derives
    ``street_keys`` and ``shape_lines``.

    Attributes:
        routes: Output of ``load.load_routes``.
        trips: Output of ``load.load_trips``.
        directions: Output of ``load.load_directions``.
        ways: The street cache (``streets.cache.read_street_cache``).
        street_keys: ``streets.street_key_table(ways)``.
        shape_lines: Every loaded shape's points.
    """

    routes: pl.DataFrame
    trips: pl.DataFrame
    directions: pl.DataFrame
    ways: pl.DataFrame
    street_keys: pl.DataFrame
    shape_lines: ShapeLines


def build_match_reference(
    *,
    routes: pl.DataFrame,
    trips: pl.DataFrame,
    directions: pl.DataFrame,
    shapes: pl.DataFrame,
    ways: pl.DataFrame,
) -> MatchReference:
    """Derive the per-run lookups once, so matching each notice is cheap.

    Args:
        routes: Output of ``load.load_routes``.
        trips: Output of ``load.load_trips``.
        directions: Output of ``load.load_directions``.
        shapes: Output of ``load.load_shapes`` (the bus feed is enough:
            the rail feed has no detours).
        ways: The street cache.

    Nothing is checked against ``trips`` here: a matched route whose shape
    is missing from ``shapes`` fails later, as a bug (wrong feed loaded).
    """
    shape_lines = {
        (feed, shape_id): coordinates
        for feed, shape_id, coordinates in shape_coordinates(shapes).iter_rows()
    }
    return MatchReference(
        routes=routes,
        trips=trips,
        directions=directions,
        ways=ways,
        street_keys=street_key_table(ways),
        shape_lines=shape_lines,
    )


def match_notice(notice: DetourNotice, reference: MatchReference) -> Detour:
    """Match a notice to its GTFS route and the shapes in its direction.

    Args:
        notice: Output of ``parse.notice.parse_detour``. Matched whatever
            its ``status``: even an ``unknown`` notice belongs to a known
            route. Filtering by status is the consumer's job.
        reference: GTFS and street data, from ``build_match_reference``.

    Returns:
        A ``Detour`` with ``notice`` unchanged and:

        - ``match=None`` and the issue ``"route: <reason>"`` if the API
          route has no GTFS route (see ``routes.find_gtfs_route``).
        - Otherwise a ``RouteMatch``. Its ``shapes`` are **all** the route's
          shapes in the notice's direction (branches and short-turns
          included; narrowing by location comes later), with no issue.
          If they can't be found, ``shapes`` is empty and there is one
          ``"shapes: ..."`` issue: no direction in the notice, the route
          has no such direction (``directions.find_direction_id``), or no
          shapes in it. Never falls back to both directions.
          Its ``start_point`` comes from ``place.find_start_point`` with
          the lines of all the route's shapes (both directions, so it
          doesn't need the notice's direction); a ``"start: ..."`` issue
          from it comes after any shapes issue.
          Its ``rejoin_point`` comes from ``place.find_rejoin_point`` with
          the notice's ``route_steps`` and the lines of its affected
          shapes only (the rejoin is on the route in the detour's
          direction); ``None`` with no issue when not found.

    Only ``ValueError`` from the lookups becomes an issue; anything else
    (e.g. a malformed frame) is a bug and propagates.
    """
    try:
        feed, route_id = find_gtfs_route(notice.source.route_id, reference.routes)
    except ValueError as err:
        return Detour(notice=notice, match=None, issues=(f"route: {err}",))

    shapes, shape_issues = _affected_shapes(
        notice.direction, feed, route_id, reference.trips, reference.directions
    )
    start_point, start_issues = find_start_point(
        notice.start_place,
        reference.ways,
        reference.street_keys,
        _route_lines(feed, route_id, reference),
    )
    rejoin_point = find_rejoin_point(
        notice.route_steps,
        reference.ways,
        reference.street_keys,
        [reference.shape_lines[(feed, shape.shape_id)] for shape in shapes],
    )
    return Detour(
        notice=notice,
        match=RouteMatch(
            feed=feed,
            route_id=route_id,
            shapes=shapes,
            start_point=start_point,
            rejoin_point=rejoin_point,
        ),
        issues=shape_issues + start_issues,
    )


def _route_lines(
    feed: Feed, route_id: str, reference: MatchReference
) -> list[list[list[float]]]:
    """Every shape of the route, both directions, each once, in trip order.

    Both directions: where a detour starts doesn't depend on which way the
    bus goes, and this works when the notice has no direction. A shape
    missing from ``shape_lines`` raises ``KeyError`` (wrong feed loaded).
    """
    shape_ids = route_shape_ids(reference.trips, feed, route_id)["shape_id"]
    return [reference.shape_lines[(feed, s)] for s in dict.fromkeys(shape_ids)]


def _affected_shapes(
    direction: Direction | None,
    feed: Feed,
    route_id: str,
    trips: pl.DataFrame,
    directions: pl.DataFrame,
) -> tuple[tuple[AffectedShape, ...], tuple[str, ...]]:
    """Return ``(shapes, issues)`` for one direction of a matched route.

    Exactly one of the two is non-empty.
    """
    if direction is None:
        return (), ("shapes: no direction in notice",)
    try:
        direction_id = find_direction_id(directions, feed, route_id, direction)
    except ValueError as err:
        return (), (f"shapes: {err}",)

    in_direction = route_shape_ids(trips, feed, route_id).filter(
        pl.col("direction_id") == direction_id
    )
    shapes = tuple(
        AffectedShape(shape_id=shape_id, direction_id=shape_direction_id)
        for shape_id, shape_direction_id in in_direction.select(
            "shape_id", "direction_id"
        ).iter_rows()
    )
    if not shapes:
        issue = (
            f"shapes: {feed} route '{route_id}' has no shapes"
            f" with direction_id {direction_id}"
        )
        return (), (issue,)
    return shapes, ()


def match_notices(
    notices: Iterable[DetourNotice], reference: MatchReference
) -> list[Detour]:
    """Match every notice: one ``Detour`` per notice, in input order.

    Unmatched notices are kept (``match=None`` plus an issue), never
    dropped, so the output always has as many items as the input. Catches
    nothing itself: like ``match_notice``, only a failed lookup becomes an
    issue, and anything else propagates.

    Args:
        notices: E.g. the output of ``parse.notice.parse_snapshot``.
        reference: From ``build_match_reference``, built once for all.
    """
    return [match_notice(notice, reference) for notice in notices]
