"""Build the street cache: OSM road ways from several extracts, combined.

Reading the raw extracts takes about 30 s; the combined table is a few tens
of MB and loads in well under a second. Bus routes change rarely, so the
cache is rebuilt by hand when the extracts are refreshed, not on every run.
"""

from collections.abc import Sequence

import polars as pl

# How many conflicting way IDs an error message lists before "and N more".
_MAX_IDS_IN_MESSAGE = 5


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
