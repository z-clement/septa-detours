"""Look up which GTFS shapes belong to a route.

Pure functions over DataFrames (no file I/O) so they can be tested with
small hand-built frames.

Join path reminder: ``routes -> trips -> shapes`` via ``route_id`` then
``shape_id``, always on ``(feed, id)``. ``trips`` already carries
``route_id``, so the ``routes`` table is not needed to go from a route to
its shapes. Join ``routes`` separately where its columns (color, names,
``route_type``) are actually used.
"""

import polars as pl

from septa_detours.gtfs.load import Feed


def route_shape_ids(trips: pl.DataFrame, feed: Feed, route_id: str) -> pl.DataFrame:
    """Return the distinct shapes used by one route's trips.

    Many trips share a few shapes (route 21: 660 trips, 2 shapes), so the
    result is deduplicated to one row per shape and direction.

    Args:
        trips: Output of ``load.load_trips``.
        feed: Which feed the route belongs to. Needed because ``route_id``
            is only unique within a feed.
        route_id: The GTFS ``route_id`` (not ``route_short_name``; they
            can differ).

    Returns:
        A frame with columns ``feed``, ``shape_id``, and ``direction_id``, one row per
        distinct shape and direction, in the order they first appear in ``trips``.
        Shaped to join onto ``shapes.shape_coordinates`` output on
        ``["feed", "shape_id"]``.

    Edge cases:
        - Unknown ``route_id`` and a route whose trips have no shapes both
          give an empty frame. This function can't tell them apart (that
          needs ``routes``); the caller decides whether empty is an error.
        - ``shape_id`` is optional in GTFS; trips with a null ``shape_id``
          have nothing to draw and should be dropped.
        - The same ``route_id`` could exist in both feeds; filter on
          ``feed`` too.
        - Null ``direction_id`` is grouped as its own value.
    """
    df = trips.filter(
        pl.col("feed") == feed,
        pl.col("route_id") == route_id,
        pl.col("shape_id").is_not_null(),
    )
    return df.select("feed", "shape_id", "direction_id").unique(maintain_order=True)
