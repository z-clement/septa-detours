"""Turn one ``DetourNotice`` into a ``Detour`` by matching it to GTFS."""

import polars as pl

from septa_detours.match.routes import find_gtfs_route
from septa_detours.model import Detour, DetourNotice, RouteMatch


def match_notice(notice: DetourNotice, routes: pl.DataFrame) -> Detour:
    """Match a notice to its GTFS route.

    Args:
        notice: Output of ``parse.notice.parse_detour``. Matched whatever
            its ``status``: even an ``unknown`` notice belongs to a known
            route. Filtering by status is the consumer's job.
        routes: Output of ``load.load_routes``.

    Returns:
        A ``Detour`` with ``notice`` unchanged and:

        - ``match=None`` and the issue ``"route: <reason>"`` if the API
          route has no GTFS route (see ``routes.find_gtfs_route``).
        - Otherwise a ``RouteMatch`` with **empty** ``shapes`` and one
          ``"shapes: ..."`` issue: compass directions (NB/SB) can't be
          mapped to GTFS ``direction_id`` (0/1) yet, and listing every
          shape would claim both directions are affected.

    Only ``ValueError`` from route lookup becomes an issue; anything else
    (e.g. a malformed ``routes`` frame) is a bug and propagates.
    """
    try:
        feed, route_id = find_gtfs_route(notice.source.route_id, routes)
    except ValueError as err:
        return Detour(notice=notice, match=None, issues=(f"route: {err}",))

    if notice.direction is None:
        shapes_issue = "shapes: no direction in notice"
    else:
        shapes_issue = (
            f"shapes: direction '{notice.direction}'"
            " not mapped to a GTFS direction_id yet"
        )
    return Detour(
        notice=notice,
        match=RouteMatch(feed=feed, route_id=route_id),
        issues=(shapes_issue,),
    )
