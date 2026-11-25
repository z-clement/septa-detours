"""Turn ``DetourNotice`` objects into ``Detour`` objects by matching to GTFS."""

from collections.abc import Iterable

import polars as pl

from septa_detours.gtfs.load import Feed
from septa_detours.gtfs.routes import route_shape_ids
from septa_detours.match.directions import find_direction_id
from septa_detours.match.routes import find_gtfs_route
from septa_detours.model import (
    AffectedShape,
    Detour,
    DetourNotice,
    Direction,
    RouteMatch,
)


def match_notice(
    notice: DetourNotice,
    routes: pl.DataFrame,
    trips: pl.DataFrame,
    directions: pl.DataFrame,
) -> Detour:
    """Match a notice to its GTFS route and the shapes in its direction.

    Args:
        notice: Output of ``parse.notice.parse_detour``. Matched whatever
            its ``status``: even an ``unknown`` notice belongs to a known
            route. Filtering by status is the consumer's job.
        routes: Output of ``load.load_routes``.
        trips: Output of ``load.load_trips``.
        directions: Output of ``load.load_directions``.

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

    Only ``ValueError`` from the lookups becomes an issue; anything else
    (e.g. a malformed frame) is a bug and propagates.
    """
    try:
        feed, route_id = find_gtfs_route(notice.source.route_id, routes)
    except ValueError as err:
        return Detour(notice=notice, match=None, issues=(f"route: {err}",))

    shapes, issues = _affected_shapes(
        notice.direction, feed, route_id, trips, directions
    )
    return Detour(
        notice=notice,
        match=RouteMatch(feed=feed, route_id=route_id, shapes=shapes, start_point=None),
        issues=issues,
    )


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
    notices: Iterable[DetourNotice],
    routes: pl.DataFrame,
    trips: pl.DataFrame,
    directions: pl.DataFrame,
) -> list[Detour]:
    """Match every notice: one ``Detour`` per notice, in input order.

    Unmatched notices are kept (``match=None`` plus an issue), never
    dropped, so the output always has as many items as the input. Catches
    nothing itself: like ``match_notice``, only a failed lookup becomes an
    issue, and anything else propagates.

    Args:
        notices: E.g. the output of ``parse.notice.parse_snapshot``.
        routes: Output of ``load.load_routes``.
        trips: Output of ``load.load_trips``.
        directions: Output of ``load.load_directions``.
    """
    return [match_notice(notice, routes, trips, directions) for notice in notices]
