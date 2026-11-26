"""Shrink GTFS shapes for the map: fewer points, shapes, and digits.

``simplify_line`` drops points, ``covering_shapes`` picks the shapes the
overview needs, ``distinct_pieces`` keeps only the parts of a direction's
shapes that aren't drawn already, ``round_line`` shortens coordinates. Pure functions on
``[lon, lat]`` lines. Distances use the shared equirectangular
approximation in ``septa_detours.geo``.
"""

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise

from shapely import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from septa_detours.export.geojson import Position
from septa_detours.geo import EARTH_RADIUS_M, distance_to_line_m, distance_to_segment

_METRES_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180

type _Box = tuple[float, float, float, float]
"""``(west, south, east, north)`` in degrees."""


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


def round_line(line: Sequence[Sequence[float]], decimals: int) -> list[Position]:
    """Round coordinates to ``decimals`` places, dropping repeats it creates.

    Use after ``simplify_line``: rounding first would shift the points it
    measures. 5 decimals is ~1 m, finer than the map's line widths.

    Args:
        line: ``[lon, lat]`` pairs in order, at least two.
        decimals: Places to keep (Python ``round``).

    Returns:
        A new list of new ``[lon, lat]`` lists. A point that rounds to the
        same position as the point before it is dropped (a zero-length
        segment); a repeat further along, like a loop's end, stays. If the
        whole line rounds to one position, that position is returned
        twice, so the result is still a valid two-point LineString.

    Raises:
        ValueError: ``line`` has fewer than two points.
    """
    if len(line) < 2:
        raise ValueError(f"a line needs at least 2 points, got {len(line)}")
    rounded: list[Position] = []
    for point in line:
        position = [round(point[0], decimals), round(point[1], decimals)]
        if not rounded or position != rounded[-1]:
            rounded.append(position)
    if len(rounded) == 1:
        rounded.append(rounded[0].copy())
    return rounded


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


def covering_shapes(
    lines: Mapping[str, Sequence[Sequence[float]]], tolerance_m: float = 20.0
) -> list[str]:
    """Choose the shapes the overview map needs to draw one route-direction.

    Longest first, a shape is kept unless every one of its points is
    within ``tolerance_m`` of some shape already kept. Short-turns and
    shapes stitched together from kept branches add nothing to the drawn
    map and are dropped; real branches are kept.

    Args:
        lines: ``shape_id`` -> ``[lon, lat]`` line, for one route-direction.
            Only points are checked, not the stretches between them, so
            pass densely-pointed lines: ``simplify_line`` output at a few
            metres (also much faster than raw shapes).
        tolerance_m: How far (metres) a point may be from a kept shape and
            still count as drawn. Exactly ``tolerance_m`` counts as drawn.

    Returns:
        The kept ``shape_id``s, longest (in metres) first. Shapes of equal
        length keep their order in ``lines``, so the first is kept and an
        identical copy after it is dropped. ``[]`` for no lines.

    Raises:
        ValueError: ``tolerance_m`` is negative or NaN, or a line has fewer
            than two points (the message names its ``shape_id``).
    """
    if not tolerance_m >= 0:
        raise ValueError(f"tolerance_m must be >= 0, got {tolerance_m}")
    for shape_id, line in lines.items():
        if len(line) < 2:
            raise ValueError(f"shape {shape_id!r} has {len(line)} point(s), needs 2")

    longest_first = sorted(
        lines, key=lambda shape_id: _length_m(lines[shape_id]), reverse=True
    )
    kept: list[tuple[str, Sequence[Sequence[float]], _Box]] = []
    for shape_id in longest_first:
        line = lines[shape_id]
        if not all(_is_drawn(point, kept, tolerance_m) for point in line):
            kept.append((shape_id, line, _widened_box(line, tolerance_m)))
    return [shape_id for shape_id, _, _ in kept]


def distinct_pieces(
    lines: Sequence[Sequence[Sequence[float]]], tolerance_m: float = 20.0
) -> list[tuple[int, list[Position]]]:
    """Draw one route-direction once: each line minus what's drawn before it.

    Shapes of one direction overlap: branches share a trunk, and copies of
    a street are digitized a metre or so apart, which shows as doubled
    lines when zoomed in (UI plan U5b). The first line is kept whole; of
    each later one, only its parts farther than ``tolerance_m`` from every
    earlier line are kept (shapely: the line minus a buffer around the
    earlier ones, in local metres), and each part that stops at that
    buffer's edge is joined to the nearest point of the earlier lines, so
    a branch meets its trunk.

    Args:
        lines: ``[lon, lat]`` lines in priority order (e.g. covering
            shapes, longest first).
        tolerance_m: How far (metres) a line may stray from earlier ones
            and still count as drawn.

    Returns:
        ``(index into lines, piece)`` pairs, in line order then along each
        line (travel order kept), as new ``[lon, lat]`` lists. A line
        wholly drawn before it gives none.

    Raises:
        ValueError: ``tolerance_m`` isn't more than 0 (or is NaN), or a line
            has fewer than two points.
    """
    if not tolerance_m > 0:
        raise ValueError(f"tolerance_m must be > 0, got {tolerance_m}")
    for index, line in enumerate(lines):
        if len(line) < 2:
            raise ValueError(f"line {index} has {len(line)} point(s), needs 2")
    if not lines:
        return []
    # Local flat metres around the lines' mean latitude (equirectangular).
    lats = [point[1] for line in lines for point in line]
    x_scale = _METRES_PER_DEGREE * math.cos(math.radians(sum(lats) / len(lats)))

    def to_metres(line: Sequence[Sequence[float]]) -> LineString:
        return LineString([(p[0] * x_scale, p[1] * _METRES_PER_DEGREE) for p in line])

    def to_lon_lat(coords: Sequence[Sequence[float]]) -> list[Position]:
        return [[x / x_scale, y / _METRES_PER_DEGREE] for x, y in coords]

    pieces: list[tuple[int, list[Position]]] = [
        (0, [[point[0], point[1]] for point in lines[0]])
    ]
    kept = to_metres(lines[0])
    for index, line in enumerate(lines[1:], start=1):
        shape = to_metres(line)
        outside = shape.difference(kept.buffer(tolerance_m))
        parts = [p for p in getattr(outside, "geoms", [outside]) if not p.is_empty]
        parts.sort(key=lambda part: shape.project(Point(part.coords[0])))
        for part in parts:
            coords = list(part.coords)
            first, last = Point(coords[0]), Point(coords[-1])
            if _at_edge(kept, last, tolerance_m):
                coords.append(_nearest_xy(kept, last))
            if _at_edge(kept, first, tolerance_m):
                coords.insert(0, _nearest_xy(kept, first))
            pieces.append((index, to_lon_lat(coords)))
        kept = kept.union(shape)
    return pieces


def _at_edge(kept: BaseGeometry, end: Point, tolerance_m: float) -> bool:
    """Whether a part's end was cut at the buffer's edge (not its line's end)."""
    return kept.distance(end) <= tolerance_m * (1 + 1e-9)


def _nearest_xy(kept: BaseGeometry, end: Point) -> tuple[float, float]:
    """The point of ``kept`` nearest ``end``: where a part joins it."""
    joint = nearest_points(kept, end)[0]
    return (joint.x, joint.y)


def _length_m(line: Sequence[Sequence[float]]) -> float:
    """A line's length in metres (projected once, like ``simplify_line``)."""
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(_to_metres(line))
    )


def _widened_box(line: Sequence[Sequence[float]], tolerance_m: float) -> _Box:
    """The line's bounding box, grown by at least ``tolerance_m`` on every side.

    A degree of longitude shrinks towards the poles, so the east-west
    margin is sized at the highest latitude the box reaches: never too
    small, so a point outside the box is always too far from the line.
    """
    lons = [point[0] for point in line]
    lats = [point[1] for point in line]
    lat_margin = tolerance_m / _METRES_PER_DEGREE
    widest_lat = max(abs(lat) for lat in lats) + lat_margin
    lon_margin = lat_margin / math.cos(math.radians(widest_lat))
    return (
        min(lons) - lon_margin,
        min(lats) - lat_margin,
        max(lons) + lon_margin,
        max(lats) + lat_margin,
    )


def _is_drawn(
    point: Sequence[float],
    kept: Sequence[tuple[str, Sequence[Sequence[float]], _Box]],
    tolerance_m: float,
) -> bool:
    """Whether ``point`` is within ``tolerance_m`` of any kept line."""
    lon, lat = point[0], point[1]
    return any(
        west <= lon <= east
        and south <= lat <= north
        and distance_to_line_m(lon, lat, line) <= tolerance_m
        for _, line, (west, south, east, north) in kept
    )
