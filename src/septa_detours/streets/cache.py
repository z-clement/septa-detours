"""Build the street cache: OSM road ways from several extracts, combined.

Reading the raw extracts takes about 30 s; the combined table is a few tens
of MB and loads in well under a second. Bus routes change rarely, so the
cache is rebuilt by hand when the extracts are refreshed, not on every run.
"""

import io
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from septa_detours.io import write_bytes_atomic
from septa_detours.streets.load import STREET_WAYS_SCHEMA, BBox

# The path assumes you run from the repo root (data/processed/ is gitignored,
# except sample_* files).
DEFAULT_STREET_CACHE = Path("data/processed/streets.parquet")

# Named in error messages when the cache is missing or out of date.
BUILD_COMMAND = "uv run python -m septa_detours.streets"

# Parquet key-value metadata keys (values are JSON strings).
_SOURCES_KEY = "septa_detours:sources"
_BBOX_KEY = "septa_detours:bbox"

# How many conflicting way IDs an error message lists before "and N more".
_MAX_IDS_IN_MESSAGE = 5

# Extra room around the outermost stops. Detours stray a few blocks at most;
# 2 km also covers streets just beyond end-of-line stops.
DEFAULT_MARGIN_M = 2000.0

# Metres per degree, chosen so that converting metres to degrees errs on the
# big side (the margin is never short). A degree of latitude is shortest at
# the equator (110,574 m; 111,035 m at Philadelphia). A degree of longitude
# is 111,320 m x cos(latitude) on a sphere with the equatorial radius,
# slightly less than on the WGS84 ellipsoid (84,832 vs 84,951 m at 40.35 N):
# again errs big. (A mean-radius sphere would give 84,737 m, i.e. 0.25% too
# small a degree; that model would make the margin about 0.1% short.)
_M_PER_DEG_LAT_MIN = 110_574.0
_M_PER_DEG_LON_AT_EQUATOR = 111_320.0


def combine_street_ways(frames: Sequence[pl.DataFrame]) -> pl.DataFrame:
    """Stack ``read_street_ways`` frames, keeping one copy of each way.

    A road crossing a state border is in both states' extracts (612 such
    ways across PA/NJ/DE in the SEPTA area, 2026-11-24, all identical).
    Rows that are identical in every column collapse to their first
    appearance; everything else keeps input order (frame by frame, then
    row by row).

    The same ``way_id`` with *different* content means the extracts are
    from different days and the way was edited in between. That raises
    instead of picking one: re-fetch so every extract is from the same day.

    Args:
        frames: Frames with ``STREET_WAYS_SCHEMA``, in priority order.
            Must not be empty (polars raises ``ValueError``).

    Returns:
        One frame with ``STREET_WAYS_SCHEMA`` and unique ``way_id``s.

    Raises:
        ValueError: If any ``way_id`` has two different versions.
    """
    combined = pl.concat(frames, how="vertical").unique(maintain_order=True)

    conflicts = (
        combined.filter(pl.col("way_id").is_duplicated())
        .get_column("way_id")
        .unique(maintain_order=True)
        .to_list()
    )
    if conflicts:
        shown = ", ".join(str(way_id) for way_id in conflicts[:_MAX_IDS_IN_MESSAGE])
        more = len(conflicts) - _MAX_IDS_IN_MESSAGE
        extra = f" and {more} more" if more > 0 else ""
        msg = (
            f"{len(conflicts)} OSM ways differ between extracts (way {shown}{extra}); "
            "re-fetch the extracts so they are all from the same day"
        )
        raise ValueError(msg)
    return combined


def service_bbox(stops: pl.DataFrame, margin_m: float = DEFAULT_MARGIN_M) -> BBox:
    """Return the box around every stop, widened by ``margin_m`` on each side.

    Used to clip the OSM extracts to SEPTA's service area. Stops without
    coordinates (station nodes, null lat/lon) are ignored.

    The margin is converted to degrees so that it is *at least*
    ``margin_m`` everywhere on the WGS84 ellipsoid (the datum of GTFS and
    OSM coordinates): latitude uses the shortest possible degree, longitude
    uses the box's edge furthest from the equator (where degrees of
    longitude are shortest). At SEPTA's latitudes the result is under 2%
    over. Not meant for boxes near a pole or crossing the antimeridian.

    Args:
        stops: A frame with ``stop_lat`` and ``stop_lon`` (Float64), e.g.
            from ``gtfs.load.load_stops``.
        margin_m: Metres to add on every side; ``0`` gives the exact extent.

    Returns:
        ``(west, south, east, north)`` in degrees.

    Raises:
        ValueError: If ``margin_m`` is negative or NaN, or no stop has
            coordinates.
    """
    if not margin_m >= 0:  # also rejects NaN
        msg = f"margin_m must be >= 0, got {margin_m!r}"
        raise ValueError(msg)

    points = stops.select("stop_lon", "stop_lat").drop_nulls()
    if points.is_empty():
        msg = "no stops with coordinates to build a bounding box from"
        raise ValueError(msg)

    west, south, east, north = points.select(
        west=pl.col("stop_lon").min(),
        south=pl.col("stop_lat").min(),
        east=pl.col("stop_lon").max(),
        north=pl.col("stop_lat").max(),
    ).row(0)

    lat_margin = margin_m / _M_PER_DEG_LAT_MIN
    south -= lat_margin
    north += lat_margin

    furthest_lat = max(abs(south), abs(north))
    m_per_deg_lon = _M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians(furthest_lat))
    lon_margin = margin_m / m_per_deg_lon
    return (west - lon_margin, south, east + lon_margin, north)


@dataclass(frozen=True)
class StreetCacheInfo:
    """Where a street cache came from, stored inside the Parquet file.

    Attributes:
        sources: The extract file names it was built from, e.g.
            ``("pennsylvania-261124.osm.pbf", ...)``. The dates in the names
            say how fresh the street data is.
        bbox: The ``(west, south, east, north)`` box the ways were clipped to.
    """

    sources: tuple[str, ...]
    bbox: BBox


def write_street_cache(
    ways: pl.DataFrame, info: StreetCacheInfo, path: Path = DEFAULT_STREET_CACHE
) -> None:
    """Write ``ways`` and ``info`` to a Parquet file, replacing any old one.

    The file is built in memory (tens of MB) and written with
    ``write_bytes_atomic``, so readers never see half a cache. ``info`` is
    stored as JSON in the file's key-value metadata.

    Args:
        ways: Combined ways, e.g. from ``combine_street_ways``.
        info: Provenance to store alongside.
        path: Destination. Defaults to ``data/processed/streets.parquet``.

    Raises:
        ValueError: If ``ways`` doesn't have ``STREET_WAYS_SCHEMA`` or has a
            repeated ``way_id`` (readers rely on both).
        OSError: If the file can't be written.
    """
    if ways.schema != STREET_WAYS_SCHEMA:
        msg = f"street ways have schema {ways.schema}, expected {STREET_WAYS_SCHEMA}"
        raise ValueError(msg)
    if ways.get_column("way_id").is_duplicated().any():
        msg = "street ways have repeated way_ids; combine them with combine_street_ways"
        raise ValueError(msg)

    metadata = {
        _SOURCES_KEY: json.dumps(list(info.sources)),
        _BBOX_KEY: json.dumps(list(info.bbox)),
    }
    buffer = io.BytesIO()
    ways.write_parquet(buffer, metadata=metadata)
    write_bytes_atomic(buffer.getvalue(), path)


def read_street_cache(path: Path = DEFAULT_STREET_CACHE) -> pl.DataFrame:
    """Read the street ways written by ``write_street_cache``.

    Raises:
        FileNotFoundError: If there's no cache yet; the message names the
            build command.
        ValueError: If the file's schema isn't ``STREET_WAYS_SCHEMA`` (e.g.
            built by an older version of this code): rebuild it.
    """
    try:
        ways = pl.read_parquet(path)
    except FileNotFoundError as err:
        msg = f"no street cache at {path}; build it with: {BUILD_COMMAND}"
        raise FileNotFoundError(msg) from err

    if ways.schema != STREET_WAYS_SCHEMA:
        msg = (
            f"street cache {path} has schema {ways.schema}, expected "
            f"{STREET_WAYS_SCHEMA}; rebuild it with: {BUILD_COMMAND}"
        )
        raise ValueError(msg)
    return ways


def read_street_cache_info(path: Path = DEFAULT_STREET_CACHE) -> StreetCacheInfo:
    """Read only the provenance stored by ``write_street_cache``.

    Raises:
        FileNotFoundError: If there's no cache yet; the message names the
            build command.
        ValueError: If the metadata is missing or malformed (not a file
            this code wrote).
    """
    try:
        metadata = pl.read_parquet_metadata(path)
    except FileNotFoundError as err:
        msg = f"no street cache at {path}; build it with: {BUILD_COMMAND}"
        raise FileNotFoundError(msg) from err

    try:
        sources = json.loads(metadata[_SOURCES_KEY])
        bbox = json.loads(metadata[_BBOX_KEY])
    except (KeyError, json.JSONDecodeError) as err:
        msg = f"street cache {path} has missing or malformed provenance metadata"
        raise ValueError(msg) from err

    sources_ok = isinstance(sources, list) and all(isinstance(s, str) for s in sources)
    bbox_ok = (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in bbox)
    )
    if not (sources_ok and bbox_ok):
        msg = f"street cache {path} has malformed provenance metadata"
        raise ValueError(msg)

    west, south, east, north = (float(v) for v in bbox)
    return StreetCacheInfo(sources=tuple(sources), bbox=(west, south, east, north))
