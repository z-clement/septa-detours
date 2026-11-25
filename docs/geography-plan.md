# Geography plan (tiers A/B/C)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

How detours get geometry. Tier A (start point) is done for
intersections; step 4 (stop closures) and tiers B/C are open.

Geography plan (agreed; tier A done for intersections: start point
stored; stop closures not yet). 170 distinct real messages: 126
turn-by-turn with a rejoin ("SB via 17th St, Left on Spring Garden St,
..., Reg Rt"), 12 turns without a rejoin (layovers), 32 stop-related
(points; `stops.txt`). GTFS shapes can't supply detour streets, so build
paths on a street network, in tiers, each useful alone:
- **A**: point at `location_start` (intersection lookup) or the closed
  stop.
- **B**: highlight the skipped part of the regular route (A + rejoin
  point snapped to the route shape). Also narrows `shapes` to the right
  branch.
- **C**: full detour path: parse the message's steps (in `parse/`), find
  the start intersection, walk each named street to its intersection with
  the next, snap the end onto the route shape. Any missing street,
  non-meeting pair, or multiple plausible meetings -> `unknown`.
Decided: street data = OSM via Geofabrik + Parquet cache (see `notes/streets.md`).
Still open: libraries for later tiers (shapely + pyproj, likely networkx;
not osmnx, not a routing engine, which picks its own streets).
Street-name matching: exact after normalizing plus a small alias table
from fixtures, not fuzzy (done: `match/streets.py`). Each tier adds
geometry to `RouteMatch` -> a `model.py` change, flag first.

Tier A steps (agreed): 1. ~~street-name normalization~~ and
~~location splitting~~; 2. ~~intersection lookup~~; 3. ~~wire into
`Detour`~~ (`node_ids` was left out of `StartPoint`; add it, a
`model.py` change, if tier C needs it); 4. stop-closure notices: point
at the stop (`load_stops`; maybe needs `location_type` from the bus feed
only, which breaks "shared columns only": ask). Step 4 is postponed
behind the map UI/UX work.
