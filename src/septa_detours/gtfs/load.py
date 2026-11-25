"""Read SEPTA GTFS tables from disk into Polars DataFrames.

Every table is read with all columns as strings, then only known-numeric
columns are cast. This protects IDs such as ``route_id`` ("124" vs "L1")
and ``shape_id`` ("001005") from type inference.

Every returned frame has a ``feed`` column ("bus" or "rail"), because IDs
are only unique within a single feed.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import polars as pl
from polars.exceptions import ColumnNotFoundError

type Feed = Literal["bus", "rail"]

ALL_FEEDS: tuple[Feed, ...] = ("bus", "rail")

# The path assumes you run from the repo root
DEFAULT_GTFS_ROOT = Path("data/gtfs")

# Columns kept from each table. Only columns present in BOTH feeds belong
# here, so the per-feed frames can be stacked with pl.concat.
ROUTE_COLUMNS = [
    "route_id",
    "route_short_name",
    "route_long_name",
    "route_type",
    "route_color",
    "route_text_color",
]
TRIP_COLUMNS = [
    "route_id",
    "service_id",
    "trip_id",
    "trip_headsign",
    "direction_id",
    "shape_id",
]
DIRECTION_COLUMNS = [
    "route_id",
    "direction_id",
    "direction",
    "direction_destination",
]
SHAPE_COLUMNS = [
    "shape_id",
    "shape_pt_lat",
    "shape_pt_lon",
    "shape_pt_sequence",
]


def feed_dir(feed: Feed, root: Path = DEFAULT_GTFS_ROOT) -> Path:
    """Return the directory that holds ``feed``'s ``.txt`` files.

    Expects ``root/<feed>/routes.txt`` etc. (no extra nesting).
    """
    return root / feed


def read_table(
    feed: Feed,
    table: str,
    columns: Sequence[str],
    root: Path = DEFAULT_GTFS_ROOT,
) -> pl.DataFrame:
    """Read one GTFS table from one feed as all-string columns.

    Keeps only ``columns`` (in that order) and adds a ``feed`` column.

    Args:
        feed: Which feed to read.
        table: Table name without extension, e.g. ``"routes"``.
        columns: Columns to keep.
        root: Directory containing the feed directories.

    Edge cases:
        - A requested column missing from this feed's file should raise a
          clear error naming the feed and table, with the column name in the attached
          original error, rather than a confusing failure later in a join.
        - Empty strings in GTFS mean "no value"; they become nulls here.
    """
    source = feed_dir(feed, root) / f"{table}.txt"
    try:
        df = pl.read_csv(source, columns=columns, infer_schema=False)
    except ColumnNotFoundError as err:
        raise ValueError(
            f"{feed} feed's {table}.txt is missing an expected column."
        ) from err
    # read_csv only nulls unquoted empty fields; quoted "" stays an empty string
    df = df.with_columns(pl.col(pl.String).replace("", None))
    return df.with_columns(pl.lit(feed).alias("feed"))


def _concat_feeds(
    feeds: Sequence[Feed],
    table: str,
    columns: Sequence[str],
    root: Path = DEFAULT_GTFS_ROOT,
) -> pl.DataFrame:
    """Load given table for the given feeds, stacked into one frame."""
    return pl.concat(
        [read_table(feed, table, columns, root) for feed in feeds], how="vertical"
    )


def load_routes(
    feeds: Sequence[Feed] = ALL_FEEDS,
    root: Path = DEFAULT_GTFS_ROOT,
) -> pl.DataFrame:
    """Load ``routes`` for the given feeds, stacked into one frame.

    Casts ``route_type`` to an integer. Note that the bus feed includes
    metro lines (L1, B1, route_type 1), so filter by ``route_type``, not
    by ``feed``, when you mean a mode.
    """
    df = _concat_feeds(feeds, "routes", ROUTE_COLUMNS, root)
    return df.with_columns(pl.col("route_type").cast(pl.Int16))


def load_trips(
    feeds: Sequence[Feed] = ALL_FEEDS,
    root: Path = DEFAULT_GTFS_ROOT,
) -> pl.DataFrame:
    """Load ``trips`` for the given feeds, stacked into one frame.

    Casts ``direction_id`` to an integer. ``shape_id`` stays a string.
    """
    df = _concat_feeds(feeds, "trips", TRIP_COLUMNS, root)
    return df.with_columns(pl.col("direction_id").cast(pl.Int8))


def load_directions(
    feeds: Sequence[Feed] = ALL_FEEDS,
    root: Path = DEFAULT_GTFS_ROOT,
) -> pl.DataFrame:
    """Load ``directions`` for the given feeds, stacked into one frame.

    ``directions.txt`` is not part of the GTFS spec; it's an extension SEPTA
    publishes, naming each ``(route_id, direction_id)``'s direction (e.g.
    route 55: ``0`` = ``"Northbound"``, ``1`` = ``"Southbound"``). Bus
    routes mostly use compass names, a few use ``"Inbound"``/``"Outbound"``
    /``"Loop"``; rail uses only ``"Inbound"``/``"Outbound"``. Some routes
    have only one row.

    Casts ``direction_id`` to an integer (the same dtype as ``load_trips``,
    so the two join without a cast). A feed without the file raises
    ``FileNotFoundError``: if SEPTA drops the extension, we should notice.
    """
    df = _concat_feeds(feeds, "directions", DIRECTION_COLUMNS, root)
    return df.with_columns(pl.col("direction_id").cast(pl.Int8))


def load_shapes(
    feeds: Sequence[Feed] = ALL_FEEDS,
    root: Path = DEFAULT_GTFS_ROOT,
) -> pl.DataFrame:
    """Load ``shapes`` for the given feeds, stacked into one frame.

    Casts ``shape_pt_lat`` / ``shape_pt_lon`` to floats and
    ``shape_pt_sequence`` to an integer. Does not sort; ordering is the
    caller's job (see ``shapes.shape_coordinates``).
    """
    df = _concat_feeds(feeds, "shapes", SHAPE_COLUMNS, root)
    return df.with_columns(
        pl.col("shape_pt_lat").cast(pl.Float64),
        pl.col("shape_pt_lon").cast(pl.Float64),
        pl.col("shape_pt_sequence").cast(pl.Int32),
    )
