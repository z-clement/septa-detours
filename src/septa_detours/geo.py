"""Approximate ground distances for lon/lat geometry (shared, not a stage).

Equirectangular: points are projected to flat metres around a reference
latitude. Accurate to well under 1% within a few kilometres, which suits
both matching (crossings near a route) and export (simplifying shapes).
Use shapely + pyproj (EPSG:2272) if real precision is ever needed.
"""

import math
from collections.abc import Sequence
from itertools import pairwise

EARTH_RADIUS_M = 6_371_008.8
"""Mean Earth radius (IUGG). With the equirectangular formula below,
distances are within ~0.3% at Philadelphia's latitude: plenty for
grouping, not for surveying."""


def metres_between(p: Sequence[float], q: Sequence[float]) -> float:
    """Approximate ground distance between two ``[lon, lat]`` points, in metres.

    Equirectangular at the points' mean latitude, mean Earth radius.
    """
    mean_lat = math.radians((p[1] + q[1]) / 2)
    dx = math.radians(q[0] - p[0]) * math.cos(mean_lat)
    dy = math.radians(q[1] - p[1])
    return EARTH_RADIUS_M * math.hypot(dx, dy)


def distance_to_line_m(
    lon: float, lat: float, line: Sequence[Sequence[float]]
) -> float:
    """Approximate ground distance from a point to a polyline, in metres.

    Args:
        lon: The point's longitude.
        lat: The point's latitude.
        line: ``[lon, lat]`` pairs in order (a GTFS shape from
            ``gtfs.shapes.shape_coordinates``). One pair is a single point.

    Returns:
        The distance to the nearest point on any segment (not just the
        nearest vertex). Vertices are projected to flat metres centred on
        the point (equirectangular), accurate to well under 1% within a few
        kilometres: plenty for matching and simplifying.

    Raises:
        ValueError: ``line`` is empty (a bug: shapes have points).
    """
    if not line:
        raise ValueError("empty line")
    scale = math.cos(math.radians(lat))
    points = [
        (
            math.radians(vertex[0] - lon) * scale * EARTH_RADIUS_M,
            math.radians(vertex[1] - lat) * EARTH_RADIUS_M,
        )
        for vertex in line
    ]
    if len(points) == 1:
        return math.hypot(*points[0])
    return min(distance_to_segment(a, b) for a, b in pairwise(points))


def distance_to_segment(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from the origin to segment ``a``-``b``, in flat coordinates.

    To measure from a point ``p``, pass ``a - p`` and ``b - p``. A
    zero-length segment (``a == b``) is just a point.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(*a)
    # Position of the origin's projection along the segment, clamped to it.
    t = max(0.0, min(1.0, -(a[0] * dx + a[1] * dy) / length_squared))
    return math.hypot(a[0] + t * dx, a[1] + t * dy)
