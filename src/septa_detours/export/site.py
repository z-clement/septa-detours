"""Build the data contract's files (``export/contract.py``) from GTFS + detours.

Pure functions: no file I/O (that's ``write.py``).
"""

import re
from collections.abc import Iterable, Sequence
from typing import Final

from septa_detours.export.contract import Bounds, Mode
from septa_detours.gtfs.load import Feed

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
