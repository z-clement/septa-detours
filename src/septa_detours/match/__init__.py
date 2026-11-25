"""Match stage: tie each ``DetourNotice`` to the GTFS network.

Input is ``model.DetourNotice`` (from ``parse/``) plus GTFS frames from
``gtfs/``; output is ``model.Detour``. Shapely/pyproj geometry, if it is
ever needed, lives here and nowhere else.

Layout:
    ``routes``: API route ID -> GTFS ``(feed, route_id)``.

Rule: never guess. A notice that can't be matched gets ``match=None`` and
an issue saying why; a wrong map is worse than an incomplete one.
"""
