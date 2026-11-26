"""The data contract: every file the web page reads, as Python types.

The page reads only these files, all under ``web/data/``; nothing else.
``docs/web-plan.md`` ("Part 1: the data contract") explains each one.
Layout::

    status.json             Status (read first: its schema_version)
    routes.json             list[RouteEntry], in display order
    network.geojson         FeatureCollection (NETWORK_PROPERTIES)
    starts.geojson          FeatureCollection (START_PROPERTIES)
    skipped.geojson         FeatureCollection (SKIPPED_PROPERTIES)
    paths.geojson           FeatureCollection (PATH_PROPERTIES)
    routes/<key>.json       RouteDetail

Each export overwrites these in place (decided: no history), one file at
a time; a page loading mid-export may rarely mix old and new files.

Plain JSON files (not GeoJSON) keep lists as lists and missing values as
explicit ``null``. In GeoJSON files, MapLibre drops null properties and
turns nested values into strings, so their properties stay flat scalars.

Bump ``SCHEMA_VERSION`` (and ``SCHEMA_VERSION`` in ``web/js/data.js``) on
any change a page already in use couldn't read (renamed or removed field,
changed meaning), or when the page starts relying on a new field (old
data would then read silently wrong: refuse it instead). Adding a file or
an optional field the page can ignore doesn't need a bump.

Versions: 1, the first contract; 2, ``routes.json`` gains
``detours.windows``; 3, tier B: the detour object gains ``rejoin_point``
and ``skipped``, and ``skipped.geojson`` is new (the page draws them);
4, tier C: the detour object gains ``path``, and ``paths.geojson`` is
new; 5, the detour object gains ``rejoin_streets`` (the card names the
rejoin).
"""

from typing import Final, Literal, TypedDict

from septa_detours.export.geojson import FeatureCollection, Position
from septa_detours.gtfs.load import Feed
from septa_detours.model import Direction, NoticeStatus

SCHEMA_VERSION: Final = 5

type Mode = Literal["metro", "trolley", "trackless", "bus", "rail"]
"""A route's mode, from GTFS ``route_type`` (see ``route_mode``)."""

type Timing = Literal["active", "upcoming", "ended", "unknown"]
"""Whether a detour is in effect at some moment. The page computes it;
``starts.geojson`` carries an export-time default for first paint."""

type Bounds = tuple[Position, Position]
"""``([west, south], [east, north])``, as MapLibre's ``fitBounds`` takes."""


class StartPointObject(TypedDict):
    """Where a placed detour starts (or rejoins): an OSM node near the route."""

    lon: float
    lat: float
    node_id: int


class DetourObject(TypedDict):
    """One detour, in route detail files and ``Status.unmatched``."""

    source_key: str
    route: str
    """A route ``key`` (``bus-21``) for matched detours; the alerts API's
    ``route_id`` (``bus_route_H``) in ``Status.unmatched``."""
    status: NoticeStatus
    direction: Direction | None
    direction_id: int | None
    """From the matched shapes when they all agree, else ``None``."""
    location_start: str | None
    location_end: str | None
    start: str | None
    """ISO 8601 with the parsed UTC offset."""
    end: str | None
    reason: str | None
    message: str
    """The raw API text."""
    issues: list[str]
    """Parse issues, then match issues."""
    start_point: StartPointObject | None
    rejoin_point: StartPointObject | None
    """Where the detour gets back on its route (tier B), or ``None``."""
    rejoin_streets: list[str] | None
    """How to name the rejoin, streets as written in the message: two
    (``["Passyunk", "17th"]``: their crossing, "at Passyunk & 17th") or
    one (``["Francis St"]``: that street leads back, "via Francis St");
    ``None`` without a rejoin (``rejoin_point`` is then ``None`` too)."""
    skipped: list[Position] | None
    """The regular route it skips, start to rejoin, ``[lon, lat]`` in
    travel order (simplified at ``DETAIL_TOLERANCE_M``, rounded), or
    ``None`` when unknown."""
    path: list[Position] | None
    """Where the detour goes (tier C), start to rejoin, ``[lon, lat]`` in
    travel order (simplified and rounded as ``skipped``), or ``None``
    when unknown."""
    shape_ids: list[str]
    """The matched shapes, in match order; ``[]`` when unmatched."""


class StatusCounts(TypedDict):
    """Every detour in the snapshot: matched to a route, and placed."""

    total: int
    matched: int
    placed: int


class Status(TypedDict):
    """``status.json``: where the build came from, and totals."""

    schema_version: int
    generated_at: str
    """When the export ran, ISO 8601 UTC."""
    snapshot: str
    """The alerts snapshot's file name."""
    snapshot_fetched_at: str | None
    """From the snapshot's stamp name (UTC); ``None`` for a hand-named one."""
    gtfs: dict[Feed, str | None]
    """Each feed's ``feed_version`` from ``feed_info.txt`` (``v202611220``);
    ``None`` when a feed has no such file or value."""
    detours: StatusCounts
    unmatched: list[DetourObject]
    """Detours whose route isn't in GTFS, listed so none silently vanish."""


type DetourWindow = tuple[str | None, str | None]
"""A detour's overall ``(start, end)``, ISO 8601 as in ``DetourObject``;
``None`` when unknown. JSON: a 2-item list."""


class RouteDetourCounts(TypedDict):
    """A route's matched detours, and how many of them are placed."""

    total: int
    placed: int
    windows: list[DetourWindow]
    """Every matched detour's window (placed or not), snapshot order, so
    the page can compute each one's ``Timing`` without the route file."""


class RouteEntry(TypedDict):
    """One row of ``routes.json`` (the sidebar's route list)."""

    key: str
    """``<feed>-<route_id>``: the only route ID the page uses."""
    feed: Feed
    route_id: str
    short_name: str
    """GTFS ``route_short_name``, or ``route_id`` when it has none."""
    long_name: str | None
    mode: Mode
    color: str | None
    """CSS ``#RRGGBB``; ``None`` when GTFS has none (the page picks one)."""
    text_color: str | None
    has_shapes: bool
    """``False`` for routes with no trips/shapes (substitution shuttles):
    listed greyed out, not drawn."""
    bounds: Bounds | None
    """``None`` exactly when ``has_shapes`` is ``False``."""
    detours: RouteDetourCounts


class DirectionEntry(TypedDict):
    """One direction of a route, from SEPTA's ``directions.txt``."""

    direction_id: int
    name: str | None
    """``"Northbound"``, ``"Inbound"``, ``"Loop"``...; ``None`` if missing."""
    destination: str | None


class RouteDetail(TypedDict):
    """``routes/<key>.json``: fetched when the page focuses a route."""

    schema_version: int
    key: str
    directions: list[DirectionEntry]
    shapes: FeatureCollection
    """Every shape of the route (``SHAPE_PROPERTIES``), not just the
    overview's covering set."""
    detours: list[DetourObject]
    """Every matched detour on the route, placed or not, snapshot order."""


NETWORK_PROPERTIES: Final = ("key", "direction_id", "mode", "color")
"""Feature properties in ``network.geojson`` (LineStrings). The rest of a
route's fields come from ``routes.json`` by ``key``."""

START_PROPERTIES: Final = ("key", "source_key", "color", "timing")
"""Feature properties in ``starts.geojson`` (Points, one per placed
detour). ``timing`` is a ``Timing``, computed at export time."""

SKIPPED_PROPERTIES: Final = ("key", "source_key", "color", "timing")
"""Feature properties in ``skipped.geojson`` (LineStrings, one per detour
with a skipped stretch), as ``START_PROPERTIES``."""

PATH_PROPERTIES: Final = ("key", "source_key", "color", "timing")
"""Feature properties in ``paths.geojson`` (LineStrings, one per detour
with a path), as ``START_PROPERTIES``."""

SHAPE_PROPERTIES: Final = (
    "shape_id",
    "direction_id",
    "trip_count",
    "covering",
    "color",
)
"""Feature properties of ``RouteDetail.shapes`` (LineStrings). ``covering``
is ``True`` for shapes in the overview's covering set."""
