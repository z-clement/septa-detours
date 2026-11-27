"""Match stage: tie each ``DetourNotice`` to the GTFS network.

Input is ``model.DetourNotice`` (from ``parse/``) plus GTFS frames from
``gtfs/`` and OSM ways from ``streets/``; output is ``model.Detour``.
Shapely/pyproj geometry lives here and nowhere else (``skipped``).

Layout:
    ``routes``: API route ID -> GTFS ``(feed, route_id)``.
    ``directions``: a notice's NB/SB/EB/WB -> GTFS ``direction_id``.
    ``notice``: assembles each ``Detour`` (route, shapes, places, path).
    ``streets``: alert street names -> OSM's spelled-out names.
    ``crossings``: where two streets' OSM ways meet ("A & B").
    ``place``: the start (tier A) and rejoin (tier B) on the streets.
    ``skipped``: the stretch of regular route a detour skips (tier B).
    ``path``, ``walk``: the detour's own path along OSM streets (tier C).
    ``__main__``: the command (parse + match one snapshot).

Rule: never guess. A notice that can't be matched gets ``match=None`` and
an issue saying why; a wrong map is worse than an incomplete one.
"""
