"""Turn GTFS shape points into ordered coordinate lists.

Pure functions over DataFrames (no file I/O) so they can be tested with
small hand-built frames.
"""

import polars as pl


def shape_coordinates(shapes: pl.DataFrame) -> pl.DataFrame:
    """Collapse shape points into one row per ``(feed, shape_id)``.

    Args:
        shapes: Output of ``load.load_shapes``.

    Returns:
        A frame with columns ``feed``, ``shape_id``, and ``coordinates``,
        where ``coordinates`` is a list of ``[lon, lat]`` pairs in
        ``shape_pt_sequence`` order. That is GeoJSON order, not GTFS's
        lat/lon column order.

    Edge cases:
        - Points may not be stored in sequence order in the file.
        - Group by ``feed`` as well as ``shape_id``: the same shape_id
          could appear in both feeds.
        - Sequence numbers can have gaps (e.g. 1, 2, 5); order by them,
          don't index by them.
    """
    # TODO: sort by sequence (before grouping, or inside the agg)
    # TODO: build a [lon, lat] pair per point
    # TODO: group by (feed, shape_id) and collect the pairs into a list
    raise NotImplementedError
