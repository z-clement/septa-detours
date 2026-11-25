"""Find where two sets of OSM ways cross: the point behind ``"A & B"``.

The ways come from ``streets.street_matches`` (after ``split_shared_ways``).
Two streets usually share one node, but a wide or divided crossing shares
several (JFK Blvd & Broad St: two nodes 62 m apart), and the same pair of
names can cross in several towns (Market & 5th: six places). Nearby shared
nodes are grouped into one ``Crossing``; far-apart groups stay separate
for the caller to choose between (e.g. by distance to the route).
"""

import math
from collections.abc import Sequence
from typing import NamedTuple

import polars as pl

from septa_detours.geo import EARTH_RADIUS_M, distance_to_line_m

CROSSING_RADIUS_M = 100.0
"""Shared nodes this close (to any node already in a group) join it.

Real name pairs (2026-11-25 alerts vs the 2026-11-24 cache) share nodes
either at most 62 m apart (one wide crossing) or over 1 km apart
(different places), never in between.
"""

ROUTE_RADIUS_M = 500.0
"""A crossing this close to any of the route's shapes can be its detour start.

Decided from real data (2026-11-25 alerts): right crossings are 0-998 m
off the route (110 of 132 within 7 m; one-way pairs and parade closure
points up to ~1 km), wrong ones (same names, other towns) always at least
1,496 m. 500 m places 127 of 132 and stays 3x inside the nearest wrong
candidate.
"""


class Crossing(NamedTuple):
    """One place where the two streets meet.

    Attributes:
        node_ids: Every shared OSM node in the group, ascending.
        node_id: The representative node: the group's node nearest the
            group's average position (a real node on both streets).
        lon: The representative node's longitude.
        lat: Its latitude.
    """

    node_ids: tuple[int, ...]
    node_id: int
    lon: float
    lat: float


def find_crossings(
    ways: pl.DataFrame,
    first: pl.DataFrame,
    second: pl.DataFrame,
    radius_m: float = CROSSING_RADIUS_M,
) -> tuple[Crossing, ...]:
    """Find every place where ``first``'s ways meet ``second``'s.

    Args:
        ways: The street cache (``streets.cache.read_street_cache``).
        first: Ways of the first street (``way_id`` column, e.g. from
            ``street_matches``).
        second: Ways of the second street.
        radius_m: Grouping distance (see ``CROSSING_RADIUS_M``).

    Returns:
        One ``Crossing`` per group of shared nodes, ordered by each
        group's smallest node ID. Empty if the ways share no node
        (including when either side has no ways); the caller decides
        what that means.
    """
    first_nodes = _way_nodes(ways, first)
    second_ids = _way_nodes(ways, second).select("node_id")
    shared = first_nodes.join(second_ids, on="node_id", how="semi").sort("node_id")
    points = [
        (node_id, lon, lat)
        for node_id, (lon, lat) in shared.select("node_id", "coordinates").rows()
    ]
    return tuple(_crossing(group) for group in _group_nearby(points, radius_m))


type _Point = tuple[int, float, float]
"""``(node_id, lon, lat)``."""


def _way_nodes(ways: pl.DataFrame, selected: pl.DataFrame) -> pl.DataFrame:
    """Distinct ``(node_id, coordinates)`` of the selected ways' nodes.

    Filters the cache to the selected ways *before* exploding, so a
    lookup never explodes all 146,871 ways. A node shared by two selected
    ways has the same coordinates in both, so either copy will do.
    """
    return (
        ways.join(selected.select("way_id"), on="way_id", how="semi")
        .select(pl.col("node_ids").alias("node_id"), "coordinates")
        .explode("node_id", "coordinates")
        .unique("node_id", keep="first")
    )


def _group_nearby(points: list[_Point], radius_m: float) -> list[list[_Point]]:
    """Single-linkage groups: points within ``radius_m`` of any member join.

    The groups are connected components, so input order doesn't change
    them (``find_crossings`` passes node-ID order only so processing is
    repeatable). Groups come out ordered by their smallest node ID,
    members in node-ID order. Quadratic, which is fine: real pairs share
    at most ~10 nodes.
    """
    groups: list[list[_Point]] = []
    for point in points:
        near = [
            group
            for group in groups
            if any(_metres_between(point, member) <= radius_m for member in group)
        ]
        merged = sorted([point, *(member for group in near for member in group)])
        groups = [group for group in groups if group not in near]
        groups.append(merged)
    return sorted(groups)


def _crossing(group: list[_Point]) -> Crossing:
    """Build a ``Crossing`` from one group of shared nodes.

    The representative is the node nearest the group's average position
    (ties: smaller node ID).
    """
    mean = (
        0,
        sum(lon for _, lon, _ in group) / len(group),
        sum(lat for _, _, lat in group) / len(group),
    )
    node_id, lon, lat = min(
        group, key=lambda point: (_metres_between(point, mean), point[0])
    )
    return Crossing(
        node_ids=tuple(point[0] for point in group),
        node_id=node_id,
        lon=lon,
        lat=lat,
    )


def _metres_between(p: _Point, q: _Point) -> float:
    """Approximate ground distance (equirectangular, mean Earth radius)."""
    mean_lat = math.radians((p[2] + q[2]) / 2)
    dx = math.radians(q[1] - p[1]) * math.cos(mean_lat)
    dy = math.radians(q[2] - p[2])
    return EARTH_RADIUS_M * math.hypot(dx, dy)


def crossings_near_route(
    crossings: Sequence[Crossing],
    lines: Sequence[Sequence[Sequence[float]]],
    radius_m: float = ROUTE_RADIUS_M,
) -> tuple[Crossing, ...]:
    """Keep the crossings within ``radius_m`` of any of the route's lines.

    Args:
        crossings: From ``find_crossings``.
        lines: The route's shapes as ``[lon, lat]`` lists (all of them,
            both directions: where a detour starts doesn't depend on which
            way the bus is going, and this works when the direction is
            unknown).
        radius_m: See ``ROUTE_RADIUS_M``.

    Returns:
        The kept crossings, in input order. Empty if ``lines`` is. Deciding
        what zero or several mean is the caller's job.

    Raises:
        ValueError: A line is empty (see ``distance_to_line_m``).
    """
    return tuple(
        crossing
        for crossing in crossings
        if any(
            distance_to_line_m(crossing.lon, crossing.lat, line) <= radius_m
            for line in lines
        )
    )
