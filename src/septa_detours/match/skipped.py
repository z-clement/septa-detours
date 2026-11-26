"""The stretch of regular route a detour skips (tier B).

Between where the detour leaves the route (``start_point``) and where it
gets back on (``rejoin_point``), measured along one of its shapes. The map
draws it differently from the rest of the route ("not served").

Geometry is done in EPSG:2272 (Pennsylvania South, US survey feet), via
pyproj, and cut with shapely; results go back to ``[lon, lat]``. Points
are measured *along* the shape, whose points run in travel order, so the
stretch keeps the shape's direction.
"""

from collections.abc import Sequence
from functools import cache

from pyproj import Transformer
from shapely import LineString, Point
from shapely.ops import substring

from septa_detours.match.crossings import ROUTE_RADIUS_M
from septa_detours.match.place import REJOIN_RADIUS_M

PA_SOUTH = "EPSG:2272"
"""State Plane Pennsylvania South (US survey feet): SEPTA's area, so
lengths and distances in it are true to well under 1%."""

METRES_PER_FOOT = 1200 / 3937
"""The US survey foot (EPSG:2272's unit), exactly."""

MAX_STRETCH_RATIO = 3.0
STRETCH_SLACK_M = 100.0
"""A stretch longer than ``MAX_STRETCH_RATIO`` x the straight distance
between its ends, plus ``STRETCH_SLACK_M``, is doubt (the shape loops
between them, or a point projected onto the wrong pass): no stretch.

From real data (snapshot ``121123Z``, 53 stretches): 46 are within 1.6x;
the rest 2.2-2.6x (winding roads: route 19's Algon Ave trips) except
route 97, 7.6 km for ends 1.9 km apart (3.9x). The slack keeps very short
stretches (ends a few metres apart) from tripping the ratio.
"""


@cache
def _transformers() -> tuple[Transformer, Transformer]:
    """``(lon/lat -> PA South, PA South -> lon/lat)``, built once.

    ``always_xy``: coordinates are ``(lon, lat)`` / ``(x, y)`` in and out,
    never EPSG:4326's official ``(lat, lon)`` axis order.
    """
    return (
        Transformer.from_crs("EPSG:4326", PA_SOUTH, always_xy=True),
        Transformer.from_crs(PA_SOUTH, "EPSG:4326", always_xy=True),
    )


def skipped_stretch(
    line: Sequence[Sequence[float]],
    start: tuple[float, float],
    rejoin: tuple[float, float],
) -> list[list[float]] | None:
    """The part of ``line`` from ``start`` to ``rejoin``, as ``[lon, lat]``s.

    Each point is projected onto the line (its nearest point on it); the
    stretch runs between the two projections, in the line's (travel)
    order, with the line's own points in between.

    Args:
        line: A shape as ``[lon, lat]`` points in travel order.
        start: Where the detour leaves the route, ``(lon, lat)``.
        rejoin: Where it gets back on, ``(lon, lat)``.

    Returns:
        The stretch (at least 2 points), or ``None`` (never a guess) when:
        ``start`` is more than ``ROUTE_RADIUS_M`` from the line or
        ``rejoin`` more than ``REJOIN_RADIUS_M`` (another shape's points),
        or the rejoin doesn't come after the start along the line (the
        other direction, or a loop measured the wrong way round), or the
        stretch is far longer than the straight distance between its ends
        (see ``MAX_STRETCH_RATIO``).

    Raises:
        ValueError: ``line`` has fewer than 2 points.
    """
    if len(line) < 2:
        raise ValueError(f"a line needs at least 2 points, got {len(line)}")
    to_feet, to_lon_lat = _transformers()
    xs, ys = to_feet.transform([p[0] for p in line], [p[1] for p in line])
    shape = LineString(zip(xs, ys, strict=True))
    start_point = Point(to_feet.transform(*start))
    rejoin_point = Point(to_feet.transform(*rejoin))

    if (
        shape.distance(start_point) * METRES_PER_FOOT > ROUTE_RADIUS_M
        or shape.distance(rejoin_point) * METRES_PER_FOOT > REJOIN_RADIUS_M
    ):
        return None
    start_along = shape.project(start_point)
    rejoin_along = shape.project(rejoin_point)
    if rejoin_along <= start_along:
        return None

    stretch = substring(shape, start_along, rejoin_along)
    straight = Point(stretch.coords[0]).distance(Point(stretch.coords[-1]))
    slack = STRETCH_SLACK_M / METRES_PER_FOOT
    if stretch.length > MAX_STRETCH_RATIO * straight + slack:
        return None
    lons, lats = to_lon_lat.transform(*stretch.xy)
    return [[lon, lat] for lon, lat in zip(lons, lats, strict=True)]
