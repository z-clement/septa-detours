# Geography plan (tiers A/B/C)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

How detours get geometry. Status (2026-11-27): tiers A, B and C are
**done** and on the map (start points, skipped stretches, detour paths;
`notes/match.md`). Open: tier A step 4 (stop closures; may not be
needed) and the tier C follow-ups at the end.

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
behind the map UI/UX work, and **may not be needed** (yours,
2026-11-26): stop closures are well signed in person; detour details
aren't, so the map's value is in the detours.

## Tier B (started 2026-11-25)

Goal (yours): make it easy to see which part of a route is detoured and
which is the regular route. Decided: tier B first (C later, building on
it); geometry with **shapely + pyproj** (project to EPSG:2272).

Measured first (snapshot `121123Z`): placing `location_end` with tier
A's code gives only 22 of 161 matched detours an end (69 ends don't
parse, 43 are segments, 21 are stop closures), so the rejoin comes from
the message instead: 117 of 157 distinct messages end in "Reg Rt".
The rejoin is the crossing of the last two streets **only if** that
crossing is near the route (route 2 "... Right on Passyunk, Left on
17th, Reg Rt": 17th is the route, so yes; "... Right on Ridge Ave, Left
on Francis St, Reg Rt": Francis isn't, so the real rejoin is further on:
unknown). Any doubt -> no rejoin.

Steps (each committed; model and contract changes flagged). All built
2026-11-25; the drawn map still needs a look by eye.
1. `parse/steps.py` (pure): `parse_route_steps(message)` -> `Step`s
   (`via` street, then each `left`/`right` street) up to "Reg Rt"; raises
   on anything unrecognized. `Step` in `model.py`.
2. `DetourNotice.route_steps` (default `()`, so old files still read;
   no issue when missing: messages aren't modeled yet, and an issue
   would make notices `partial`).
3. match: `rejoin_point` = the last two streets' crossing near the route
   (tier A's placement); `RouteMatch.rejoin_point`.
4. match: the skipped stretch: on the affected shapes, the part between
   the start and rejoin points (shapely, EPSG:2272); `RouteMatch.skipped`.
5. contract (schema 3) + export: the detour object gets `rejoin_point`
   and `skipped`; an overview file for the skipped lines.
6. web: draw the skipped stretch in its own style ("not served"), the
   regular route solid.

Results and decisions made while building (tier B):
- Steps: 107 of 157 distinct real messages give a path (25 have no
  `via`: stop closures; 15 no `Reg Rt`: layovers; 10 garbled, e.g.
  "Stay on Ridge Ave", "Left on Around 30th St", "Morton Ave turns to
  Chester Pk"). Stop words kept to what tests pin: `on` (any `on` that
  isn't `Left on`/`Right on` is an unknown instruction) and `around`.
- No parse issue for a missing path (it would make notices `partial` and
  move every pin); revisit with the other message questions.
- `REJOIN_RADIUS_M = 30`: last-two-streets crossings are 0-15 m from the
  affected shapes in 66 detours, the next at 62 m. 65 rejoins.
- Stretch (shapely + pyproj, EPSG:2272): projections onto the shape,
  rejoin must come after start; doubt -> none when the stretch is over
  3x its ends' distance + 100 m (drops route 97's 7.6 km for 1.9 km).
  First affected shape that gives one (lengths differ between shapes in
  5 of 51). 51 stretches, 2 m simplified: 456 points, 18 KB.
- Map: the route drawn whole, its skipped stretch faded out (a white
  wash at 65% over it, butt caps), only for detours in effect (active or
  unknown: an upcoming or ended stretch is served now); same offset;
  stretches click like dots; legend top left. (First tried: white
  casing + timing-colored dashes, then dashes down the route's middle;
  you wanted the regular route visible and the skipped part faded.)
- Next (your choice, 2026-11-26): tier C, the detour's own path, drawn
  in its own style next to the faded stretch.

Tier B follow-ups (not built):
- ~~A rejoin when the last street isn't the route (98 crossings sat
  62-959 m off): walk the last street to where it meets the route (a
  first step of tier C).~~ (done in tier C: `walk_to_route`.)
- The 6 detours with both points but no stretch: 5 have the rejoin at
  the start crossing itself (two-step paths like "via Harbison, Right
  on Frankford"): maybe "the route between start and the next crossing
  of the last street" (tier C territory).
- ~~Show the rejoin on the focused map and name it on the card~~ (done
  2026-11-26: `RouteMatch.rejoin_by`, contract 5 `rejoin_streets`, "Back
  on route at A & B" / "via A", a small end dot on the focused map).

## Tier C (started 2026-11-26)

Goal (yours): draw the detour's own path, in its own style, next to the
faded skipped stretch.

Measured first (scratch script; snapshots `121123Z` / `141550Z`): walk
the message street by street: from the start point, along each street's
OSM ways (shortest path on that street alone) to the nearest crossing
with the next street.
- 97 / 48 detours have a path and a start point; the start is the first
  two streets' crossing in 90 / 43 (the `via` street is the route).
- Walked to the end: 65 / 38. Of those with a tier B rejoin (45 / 30),
  every walk ends exactly on the rejoin node.
- Turns: the walk's left/right agrees with the message at 119 of 120
  crossings (14 legs too short to tell); the one disagreement is the MFO
  shuttle's Schuylkill -> Arch.
- Legs: median 450 m, 90th percentile 1.3 km, longest 2.5 km (Verree Rd).
- Failures (`121123Z`, 32): 16 are Penn Square (`S Penn Sq` vs OSM
  `South Penn Square`: `Sq` isn't a known street type), 4 have the start
  point off the first turn street, the rest messy (`31st` & `34th` never
  cross; no `Pattison` & `Pennrose` crossing; no `W Brown St` way;
  `Tinicum Blvd` doesn't reach `88th St`).

Decided (2026-11-26):
- Shortest paths with **networkx** (new dependency).
- No tier B rejoin: keep walking the last street until it comes within
  `REJOIN_RADIUS_M` of the affected shapes; that point ends the path and
  is the rejoin (tier B's first follow-up). Never close: no path.
- Fix street-name matching for `Sq`/`Square` (and spelled-out
  directions) first, in `match/streets.py`; it moves tier A's pins too.

Doubt rules (proposed): nearest reachable crossing at each turn; a turn
whose direction disagrees with the message -> no path (read over ~100 m
of each leg, not the segments at the node); with a tier B rejoin, the
path must end on it.

Steps (each committed; model and contract changes flagged):
1. ~~`match/streets.py`: `Sq` = Square, and alert `S`/`N`/`E`/`W` =
   the direction, so `S Penn Sq` finds `South Penn Square`~~ (done: no
   pins moved, no start changed; walked 65 -> 80 on `121123Z`; turns
   read over ~100 m all agree: see `notes/match.md`).
2. ~~Add networkx; `match/walk.py`: one street's graph and the walk
   between two node sets~~ (done, plus `turn_side`).
3. ~~The whole path from the steps (doubt rules), and the extension to
   the route when there's no rejoin~~ (done: `match/path.py`). Decided
   on the way: without a rejoin, a corner already within 30 m of the
   route -> no path (6 real cases, 5 two-street paths). Real `121123Z`:
   63 paths of 97 candidates, 22 of them with a rejoin tier B lacked.
   Follow-up: check the first turn (off the route) and a one-node last
   leg's turn against the route shape's direction.
   Follow-up (yours, 2026-11-26, seen on route 79 by eye): **the start
   can sit off the route**, so the path begins in mid-air. Route 79's
   "EB via Graysferry, Right on Washington, ..." starts at Graysferry &
   Washington, ~150 m past where the route turns off Grays Ferry; the
   path should begin where the bus leaves the route. Fix: a lead-in leg,
   walking `steps[0]` (the `via` street) from where it leaves the
   affected shapes (within `REJOIN_RADIUS_M`) to the start node, same
   doubt rules; prepend it to `RouteMatch.path`. Measure first how many
   starts sit > 30 m off their affected shapes.
4. ~~`RouteMatch.path` (model change), filled by `match_notice`~~ (done:
   a path's rejoin fills `rejoin_point`; real `121123Z` stretches 53 -> 75).
5. ~~Contract schema 4: the detour object's `path`, a `paths.geojson`~~
   (done; `data.js` loads it, nothing draws it yet).
6. ~~web: draw the path in its own style~~ (done; your choices: dashed
   in the route's color over a white casing; only detours in effect, as
   the fade). Map side not yet checked by eye.
