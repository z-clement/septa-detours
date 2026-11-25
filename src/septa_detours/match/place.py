"""Place a notice's start location on the street network (tier A).

Chains ``match/streets.py`` (alert names -> OSM ways) and
``match/crossings.py`` (ways -> crossings near the route) into one result
for ``match/notice.py``.
"""

from collections.abc import Sequence

import polars as pl

from septa_detours.match.crossings import (
    ROUTE_RADIUS_M,
    crossings_near_route,
    find_crossings,
)
from septa_detours.match.streets import split_shared_ways, street_matches
from septa_detours.model import Intersection, Location, StartPoint


def find_start_point(
    place: Location | None,
    ways: pl.DataFrame,
    keys: pl.DataFrame,
    lines: Sequence[Sequence[Sequence[float]]],
) -> tuple[StartPoint | None, tuple[str, ...]]:
    """Find the one street crossing where a detour starts, near its route.

    Args:
        place: The notice's ``start_place``.
        ways: The street cache (``read_street_cache``).
        keys: ``street_key_table(ways)``, built once per run.
        lines: Every shape of the matched route as ``[lon, lat]`` lists,
            both directions.

    Returns:
        ``(point, issues)``; exactly one of them is empty/``None``, except
        that a ``None`` place gives ``(None, ())`` (parse already flagged
        an unrecognized start; a blank one is normal). Otherwise:

        - a segment: not placed yet (needs tier B), one issue;
        - no ``lines``: nothing to check against, one issue;
        - the two streets never share an OSM node, or none of the
          crossings is within ``ROUTE_RADIUS_M`` of a line, or several
          are: one issue each, naming the streets as written. Never
          guesses between several.
    """
    if place is None:
        return None, ()
    if not isinstance(place, Intersection):
        return None, ("start: segments are not placed yet",)
    if not lines:
        return None, ("start: route has no shapes to compare with",)

    first_name, second_name = place.streets
    first, second = split_shared_ways(
        street_matches(keys, first_name), street_matches(keys, second_name)
    )
    streets = f"'{first_name}' and '{second_name}'"
    crossings = find_crossings(ways, first, second)
    if not crossings:
        return None, (f"start: no crossing of {streets} in OSM",)

    near = crossings_near_route(crossings, lines)
    within = f"within {ROUTE_RADIUS_M:g} m of the route"
    if not near:
        return None, (f"start: no crossing of {streets} {within}",)
    if len(near) > 1:
        return None, (f"start: {len(near)} crossings of {streets} {within}",)

    (crossing,) = near
    point = StartPoint(node_id=crossing.node_id, lon=crossing.lon, lat=crossing.lat)
    return point, ()
