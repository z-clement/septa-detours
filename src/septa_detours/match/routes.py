"""Map alerts-API route IDs to GTFS routes.

The alerts API names routes like ``bus_route_21`` and still uses some
pre-2025 names (``rr_route_mfo``, ``trolley_route_15``) that GTFS has
renamed (``L1_OWL``, ``G1``). Only renames backed by evidence are aliased;
everything else must match a GTFS ``route_id`` exactly or is unmatched.
"""

import polars as pl

from septa_detours.gtfs.load import Feed

API_ROUTE_ALIASES: dict[str, tuple[Feed, str]] = {
    # SEPTA Metro rebrand. Owl buses: GTFS long name "Midnight-5am Service
    # (Bus) for L1" / "... for B1".
    "rr_route_mfo": ("bus", "L1_OWL"),
    "rr_route_bso": ("bus", "B1_OWL"),
    "rr_route_mfl": ("bus", "L1"),
    "rr_route_nhsl": ("bus", "M1"),
    # Trolleys: D1/D2 long names are "Route 101"/"Route 102"; the others
    # were checked by stop names on each old route's main street
    # (2026-11-25 GTFS).
    "trolley_route_10": ("bus", "T1"),  # Lancaster Av
    "trolley_route_34": ("bus", "T2"),  # Baltimore Av
    "trolley_route_13": ("bus", "T3"),  # Chester Av
    "trolley_route_11": ("bus", "T4"),  # Woodland Av
    "trolley_route_36": ("bus", "T5"),  # Elmwood Av
    "trolley_route_15": ("bus", "G1"),  # Girard Av
    "trolley_route_101": ("bus", "D1"),
    "trolley_route_102": ("bus", "D2"),
    # Deliberately absent:
    # - rr_route_bsl: one API route, three GTFS routes (B1, B2, B3).
    # - Bus Revolution renames (H, L, R, ...): not documented in GTFS.
}
"""API route ID -> GTFS ``(feed, route_id)`` for routes SEPTA renamed."""

NAME_MATCH_PREFIXES = ("bus_route_", "trolley_route_")
"""API prefixes whose remainder may be a bus-feed GTFS ``route_id``."""


def find_gtfs_route(api_route_id: str, routes: pl.DataFrame) -> tuple[Feed, str]:
    """Return the GTFS ``(feed, route_id)`` for an alerts-API route ID.

    Tries ``API_ROUTE_ALIASES`` first, so a renamed route keeps its alias
    even if GTFS later reuses the old name. Otherwise, an ID starting with
    one of ``NAME_MATCH_PREFIXES`` matches the bus-feed route whose
    ``route_id`` equals the rest (exactly, case-sensitive):
    ``bus_route_21`` -> ``("bus", "21")``.

    Args:
        api_route_id: The API's ``route_id``, verbatim.
        routes: Output of ``load.load_routes``. Must include the bus feed
            for anything to match.

    Raises:
        ValueError: No alias and no name match, or the alias target is not
            in ``routes``. Rail (``rr_route_*`` without an alias), ``APP``,
            ``cct``, ``generic`` and retired routes all end up here.
    """
    if api_route_id in API_ROUTE_ALIASES:
        feed, route_id = API_ROUTE_ALIASES[api_route_id]
    else:
        prefix = next(
            (p for p in NAME_MATCH_PREFIXES if api_route_id.startswith(p)), None
        )
        if prefix is None:
            raise ValueError(f"no GTFS route for API route '{api_route_id}'")
        feed, route_id = "bus", api_route_id.removeprefix(prefix)

    found = routes.filter(
        (pl.col("feed") == feed) & (pl.col("route_id") == route_id)
    ).height
    if found == 0:
        raise ValueError(
            f"no GTFS route for API route '{api_route_id}'"
            f" (looked for {feed} route '{route_id}')"
        )
    return feed, route_id
