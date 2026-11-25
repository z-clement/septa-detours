"""Shrink GTFS shapes for the map: fewer points, shorter coordinates.

Pure functions on ``[lon, lat]`` lines. Distances use the shared
equirectangular approximation in ``septa_detours.geo``.
"""

import math
from collections.abc import Sequence

from septa_detours.export.geojson import Position
from septa_detours.geo import EARTH_RADIUS_M, distance_to_segment


def simplify_line(
    line: Sequence[Sequence[float]], tolerance_m: float
) -> list[Position]:
    """Drop points that barely change a line's shape (Douglas-Peucker).

    Args:
        line: ``[lon, lat]`` pairs in order, at least two.
        tolerance_m: How far (metres) a point may lie from the simplified
            line and still be dropped. ``0`` drops only points exactly on
            the line (e.g. a repeated point).

    Returns:
        A new list of new ``[lon, lat]`` lists, a subset of ``line`` in
        its order. The first and last points are always kept, so a line
        never shrinks below two points. A point is kept only if it lies
        *more* than ``tolerance_m`` from the segment joining its kept
        neighbours; exactly ``tolerance_m`` is dropped. When two points
        tie for farthest, the line is split at the earlier one.

        Distances are to the *segment*, not the infinite line through its
        ends, so a loop whose first and last points are the same keeps its
        far side.

    Raises:
        ValueError: ``line`` has fewer than two points, or ``tolerance_m``
            is negative or NaN.
    """
    if len(line) < 2:
        raise ValueError(f"a line needs at least 2 points, got {len(line)}")
    if not tolerance_m >= 0:
        raise ValueError(f"tolerance_m must be >= 0, got {tolerance_m}")

    flat = _to_metres(line)
    keep = [False] * len(line)
    keep[0] = keep[-1] = True
    # Index ranges still to split; a stack instead of recursion, so long
    # shapes can't hit Python's recursion limit.
    pending = [(0, len(line) - 1)]
    while pending:
        first, last = pending.pop()
        farthest, farthest_m = None, -1.0
        for index in range(first + 1, last):
            distance = _distance_to_chord(flat[index], flat[first], flat[last])
            if distance > farthest_m:
                farthest, farthest_m = index, distance
        if farthest is not None and farthest_m > tolerance_m:
            keep[farthest] = True
            pending.append((first, farthest))
            pending.append((farthest, last))
    return [
        [point[0], point[1]] for point, kept in zip(line, keep, strict=True) if kept
    ]


def _to_metres(line: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    """Project to flat metres from the first point, scaled at the mean latitude."""
    origin_lon, origin_lat = line[0][0], line[0][1]
    mean_lat = sum(point[1] for point in line) / len(line)
    scale = math.cos(math.radians(mean_lat))
    return [
        (
            math.radians(point[0] - origin_lon) * scale * EARTH_RADIUS_M,
            math.radians(point[1] - origin_lat) * EARTH_RADIUS_M,
        )
        for point in line
    ]


def _distance_to_chord(
    point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance from ``point`` to segment ``a``-``b`` (all flat metres)."""
    return distance_to_segment(
        (a[0] - point[0], a[1] - point[1]), (b[0] - point[0], b[1] - point[1])
    )
