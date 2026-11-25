"""Map a notice's compass direction (NB/SB/EB/WB) to a GTFS ``direction_id``.

GTFS itself only has ``direction_id`` 0/1. SEPTA's ``directions.txt``
extension (``gtfs.load.load_directions``) names each one, e.g. route 55:
``0`` = ``"Northbound"``. A notice's direction is looked up there exactly.
"""

import polars as pl

from septa_detours.gtfs.load import Feed
from septa_detours.model import Direction

COMPASS_NAMES: dict[Direction, str] = {
    "NB": "Northbound",
    "SB": "Southbound",
    "EB": "Eastbound",
    "WB": "Westbound",
}
"""``Direction`` -> its spelling in ``directions.txt``."""


def find_direction_id(
    directions: pl.DataFrame, feed: Feed, route_id: str, direction: Direction
) -> int:
    """Return the ``direction_id`` SEPTA names ``direction`` on this route.

    Args:
        directions: Output of ``load.load_directions``.
        feed: The route's feed.
        route_id: GTFS ``route_id``.
        direction: The notice's compass direction.

    Raises:
        ValueError: The route has no such direction (e.g. route 68 runs
            Northbound/Southbound but a message says "EB Via Tinicum", or
            the route uses Inbound/Outbound/Loop), has no rows at all, or
            has the direction more than once. Never guesses a nearest one.
    """
    name = COMPASS_NAMES[direction]
    on_route = directions.filter(
        (pl.col("feed") == feed) & (pl.col("route_id") == route_id)
    )
    found = on_route.filter(pl.col("direction") == name)
    if found.height == 1:
        return int(found["direction_id"].item())

    label = f"{feed} route '{route_id}'"
    if found.height == 0:
        available = ", ".join(on_route["direction"].drop_nulls().to_list()) or "none"
        raise ValueError(f"{label} has no {name} direction (has {available})")
    raise ValueError(f"{label} has {found.height} {name} directions")
