# Notes: match stage (`match/`)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Notices -> `Detour`: GTFS route + direction + shapes, street-name
normalization, OSM crossings, and the tier A start point.

Done: `match/routes.py::find_gtfs_route(api_route_id, routes) ->
(feed, route_id)` (raises `ValueError`). `API_ROUTE_ALIASES` first (12
Metro renames, decided by me: "Metro rebrand only"): `rr_route_mfo` ->
`L1_OWL`, `rr_route_bso` -> `B1_OWL`, `rr_route_mfl` -> `L1`,
`rr_route_nhsl` -> `M1`, trolleys 10/34/13/11/36 -> `T1`-`T5`, 15 ->
`G1`, 101/102 -> `D1`/`D2` (T/G1 checked by stop names on each old
route's main street). Alias wins over name match (GTFS could reuse an
old name). Otherwise `bus_route_X`/`trolley_route_X` -> bus-feed `X`,
exact and case-sensitive; `rr_*`/`APP`/`cct`/`generic` never
name-match. Alias targets must exist in `routes` too. Deliberately
unaliased: `rr_route_bsl` (one API route = B1/B2/B3) and Bus Revolution
renames. Evidence for later: L -> 51 is strong (51 serves both ends of
L's detour); R -> K weak (one shared stop); H unknown. 136/149
name-matched detours' first street is served by the matched route; the
misses are spellings, so no sign of reused names. The API's `route`
field (`AIR`, `LAN` = rail GTFS IDs) isn't kept by `ApiRoute`/`SourceText`;
only matters for rail (no detours seen).

Done: `match/directions.py::find_direction_id(directions, feed,
route_id, direction) -> int`. `COMPASS_NAMES` (NB -> "Northbound", ...),
exact match on `(feed, route_id, name)`. 0 rows -> `ValueError("bus
route '68' has no Eastbound direction (has Northbound, Southbound)")`
(`(has none)` for an unknown route; nulls skipped); 2+ -> `ValueError`.
Never picks a nearest direction.

Done: `match/notice.py`. `match_notice(notice, routes, trips,
directions) -> Detour`; `match_notices(...)` = one per notice, input
order, unmatched kept, equal notices not deduplicated, catches nothing.
- Route lookup fails -> `match=None`, issue `"route: <reason>"`;
  trips/directions are not read.
- Otherwise private `_affected_shapes` -> `(shapes, issues)`, exactly one
  non-empty: no direction -> `"shapes: no direction in notice"`; lookup
  fails -> `"shapes: <reason>"` (decided by me: empty + issue, never
  both directions); else every `route_shape_ids` row with that
  `direction_id`, in trip order, no issue; none -> `"shapes: bus route
  '55' has no shapes with direction_id 1"`.
- Every notice is matched whatever its `status`; parse issues stay on
  `notice.issues`, match issues on `Detour.issues`. Only `ValueError`
  becomes an issue.
- Known gap: `shapes` = all shapes in that direction, branches and
  short-turns included (route 55 SB: 6). `RouteMatch`'s docstring says
  "shapes the detour affects"; consider rewording in `model.py` (flag
  first). Narrowing needs location (tier B, `../geography-plan.md`).
Real snapshots: `025344Z` 126/140 get shapes (7 no direction, 5 no route:
H, L, R, 2 route 68 "EB Via Tinicum" on a N/S route); `121123Z` 152/166
(same 7/5/2).
Tests: `test_match_routes.py` (53), `test_match_directions.py` (21),
`test_match_notice.py` (28; one `gtfs` fixture = `(routes, trips,
directions)` from real rows for all 17 fixture routes; trips interleave
directions so a missing filter can't pass). Pins that break on purpose
when a fixture is added: `FIXTURE_EXPECTED` (routes), the sweep's 65 and
`NO_SHAPES` (notice), plus parse's `NOT_COMPLETE`. Shared builders in
`tests/conftest.py`: `routes_from_ids`, `trips_from_rows`,
`directions_from_rows` (fixtures returning callables; `test_geojson.py`
and `test_routes.py` keep their own, differently shaped helpers).
Mutations: routes 14/16 (2 equivalent: prefix anywhere / any case, since
`removeprefix` only strips a true prefix), directions 14/15 (`int()`
around `.item()` is redundant but kept for typing), notice 10 + 7 + 13,
all caught. 540 tests total.

Done: street-name normalization, `match/streets.py` (written by Claude
in reviewed increments; rules decided by me from a probe of the 170 real
locations vs the 40,003 cache names).
- `split_street_type(name) -> StreetName(base, street_type)`: delete dots,
  casefold, collapse whitespace, replace whole words via `WORD_ALIASES`,
  then split a known type off the **last** word only (`St Elizabeth
  Drive`: the leading St is Saint). A name that is only a type word stays
  the base (never an empty base); blank -> `ValueError`. Used for alert
  text and OSM names alike.
- `STREET_TYPES`: only what the data needs (Street, Avenue, Road,
  Boulevard, Drive, Lane, Pike + `st ave av rd blvd dr ln pk`; `Pk` =
  Pike). Park/Ferry/Ridge left out on purpose: they're name words
  (`Hunting Park`). Square (+ `sq`) added 2026-11-26 for tier C: see
  below.
- `osm_street_keys(osm_name)`: full key first, plus the key without a
  leading North/South/East/West **if the base has more words** (`South
  Street` keeps one key). Decided: prefixes dropped **on the OSM side
  only** (alert `South & 33rd` is South Street); full words only (OSM
  single letters are letter streets: `E Street`, `W Street`); trailing
  directions (`Broad Street North`) not stripped. Extra candidates
  (`West Chester Pike` -> `chester pike`, a different road) are left for
  the route check. 4,135 names get a second key.
- Decided: a type is **optional, but strict if given** (alert `JFK Blvd`
  doesn't match OSM `JFK Drive`; bare `JFK` does). Consequence: `Midvale
  Ave Btwn Fox St & Henry St` won't match (OSM has Henry Avenue).
- `WORD_ALIASES` (decided: applied to **both sides**; 14 entries, each
  from a real value): `jfk`, `mt`, `prk`, `graysferry`, `malvernave`, and
  typos `batrum creshem farimount krestown lorretto riggold schuykill
  graden sping` (OSM itself has `Schuykill Parkway`). One pass: no
  replacement word is a key. Deliberately absent: `garney` (route 54;
  probably Garnet St, unverified), `health science` (would need phrase
  aliases).
- Tests `tests/test_match_streets.py`: an `ALIAS_EVIDENCE` table of
  (real alert piece, real OSM name) pairs, checked with a test helper
  `alert_matches_osm` (same base; alert type None or equal; the real
  matcher in step 2 should follow it); a test that every alias has
  evidence. Probe after: of 198 alert name pieces, 10 find no OSM base
  (Garney, Health Science, landmarks, and splitting artifacts), 0 type
  mismatches.

Done: intersection lookup (tier A step 2), all pure, written by Claude in
reviewed increments. How the pieces chain (this is what step 3 wires up):
```
keys = street_key_table(ways)                   # once per run (0.07 s)
first, second = split_shared_ways(
    street_matches(keys, a), street_matches(keys, b))  # a, b = start_place.streets
crossings = find_crossings(ways, first, second)  # 2-12 ms per pair
near = crossings_near_route(crossings, lines)    # lines = all route shapes
```
`ways` = `read_street_cache()`; `lines` = `shape_coordinates(...)`
`coordinates` for every `route_shape_ids` row of the route (both
directions), as `list[list[float]]`.
- `match/streets.py::street_key_table(ways)`: one row per
  `(way_id, base, street_type, prefix_dropped)` (`STREET_KEYS_SCHEMA`),
  way order, full key first. `osm_street_keys` runs once per distinct
  name (40,003, not 146,871). A blank-normalizing name raises naming the
  first way. Real cache: 168,983 rows, 3.5 MB.
- `street_matches(keys, name)` -> `(way_id, specificity)`
  (`STREET_MATCH_SCHEMA`). The matching rule: same base; a type in the
  alert must equal the way's. Specificity 0..3 = 2 if the way's **full**
  name matched (not its prefix-less key) + 1 if the alert gave a type.
- `split_shared_ways(first, second)`: decided (mine): a way matching
  **both** names goes to the side with higher specificity (full name
  beats prefix-less, then typed beats untyped); a tie goes to the
  **first-listed** name (both names are then the same street, so the
  second side is left without it and no self-crossing is found). No real
  pair hits this (0 of 171); it's a guard.
- `match/crossings.py::find_crossings(ways, first, second, radius_m=100)`:
  semi-joins the cache to each side's ways *before* exploding nodes;
  shared nodes grouped by single linkage within `CROSSING_RADIUS_M = 100`
  (evidence: real shared nodes are <= 62 m apart for one crossing, or
  > 1 km for different places; nothing between). One `Crossing(node_ids,
  node_id, lon, lat)` per group, ordered by smallest node ID. Decided
  (mine): the representative `node_id` is the group's **real node nearest
  the group's average** (tie: smaller ID), so tier C can walk from it.
  `()` if nothing is shared.
- `distance_to_line_m(lon, lat, line)`: point to polyline, nearest point
  on any segment; local equirectangular metres, mean Earth radius
  (`EARTH_RADIUS_M`); empty line -> `ValueError`. Private
  `_metres_between` (grouping) uses the same approximation. **Since
  moved** (2026-11-25, my choice) to the shared `septa_detours/geo.py`
  with `EARTH_RADIUS_M`, so `export/simplify.py` can use it without
  importing a stage; its tests moved to `tests/test_geo.py`.
- `crossings_near_route(crossings, lines, radius_m=500)`: keeps crossings
  within `ROUTE_RADIUS_M = 500` of **any** line, input order. Decided
  (mine) from data: right crossings are 0-998 m off the route (110/132
  within 7 m; one-way pairs ~113 m; parade closure points up to ~1 km),
  wrong ones (other towns; Camden's Market St) >= 1,496 m. 500 m places
  127/132 and stays 3x inside the nearest wrong one. All shapes, both
  directions: the start point doesn't depend on direction, and it works
  when direction is unknown.
- Tests: `test_match_streets.py` (key table, matches, split; a
  `make_ways` helper and a `BROAD_WAYS` set), `test_match_crossings.py`
  (34; hand-built ways near 17th & Washington; distances checked against
  hand-worked values: at that latitude 0.001 deg = 85.27 m east, 111.20 m
  north). Mutation survivors are all documented equivalents
  (`maintain_order` on joins polars happens to keep; a redundant Int8
  cast; the node sort before grouping, since groups are connected
  components). Test lesson: a "tie" must be binary-exact
  (multiples of 2**-12 deg) or float error hides the tie-break; a radius
  test needs a diagonal case or Manhattan distance survives.
  1034 tests total.
- Real end-to-end (scratch script, not committed), per snapshot
  `025344Z` / `121123Z`: placed 110 / 134; start not an intersection
  (segment, unrecognized, blank) 16 / 17; API route not in GTFS 5 / 5;
  no OSM crossing at all 4 / 4 (`Garney & Lehigh`, `Malvern Ave &
  Wynnewood Ave` (OSM may say Wynnewood Road), `Huntingdon Pk & Station
  Dr`, `Easton Rd & Old York Rd`: not investigated); crossings exist but
  none within 500 m 5 / 6 (the parade points); **ambiguous (2+ within
  500 m) 0 / 0**.

Done: tier A wired into `Detour` (written by Claude in four reviewed
increments).
- `model.py`: `StartPoint(node_id, lon, lat)`: `node_id` strict int
  `> 0` (real OSM IDs are positive), `lon` in [-180, 180], `lat` in
  [-90, 90] (the bounds also reject NaN/inf); named fields, not a pair.
  `RouteMatch.start_point: StartPoint | None` is **required, no
  default** (decided by me, like `start_place`): forgetting the lookup
  can't pass for "not found". `None` = not placed; the reason is in
  `Detour.issues`, unless the notice has no start place at all.
- `match/place.py::find_start_point(place, ways, keys, lines) ->
  (StartPoint | None, issues)`. Exactly one of them is empty, except a
  `None` place -> `(None, ())` (parse already flagged it, or it was
  blank). Issues (wording agreed): `"start: segments are not placed
  yet"` (segments wait for tier B: guessing which end is wrong half the
  time); `"start: route has no shapes to compare with"`; `"start: no
  crossing of 'A' and 'B' in OSM"`; `"start: no crossing of 'A' and 'B'
  within 500 m of the route"`; `"start: N crossings of 'A' and 'B'
  within 500 m of the route"` (never guesses). Names quoted as the alert
  wrote them; `500` comes from `ROUTE_RADIUS_M`.
- `match/notice.py`: `MatchReference` (frozen, **keyword-only**
  dataclass, decided by me: five frames of one type can't be swapped by
  position): `routes`, `trips`, `directions`, `ways`, `street_keys`,
  `shape_lines` (`(feed, shape_id)` -> `[[lon, lat], ...]`, type
  `ShapeLines`). `build_match_reference(*, routes, trips, directions,
  shapes, ways)` runs `street_key_table` and `shape_coordinates` **once
  per run**; load only the bus feed (rail has no detours). Signatures
  are now `match_notice(notice, reference)` /
  `match_notices(notices, reference)`.
- `match_notice` looks the start point up for **every matched route**,
  with private `_route_lines`: every shape of the route, **both
  directions**, each once, in trip order (so a notice with no direction
  is still placed). Issue order: shapes, then start. An unmatched route
  reads no streets or shapes. A trip shape missing from `shape_lines`
  raises `KeyError` (a bug: wrong feed loaded), not an issue.
Tests: `test_model.py` (`make_start_point`; bounds and bad values),
`test_match_place.py` (hand-built ways around 17th & Washington; traps:
a far crossing with the *smaller* node ID, `Ridge` & `Ridge Ave` sharing
ways, a three-node crossing whose representative is the middle node),
`test_match_notice.py`. Its `reference` fixture now holds invented
streets for two crossings (17th & Washington: route 2 runs on 17th;
Broad & Chestnut: route 31 on Chestnut) and a placeholder line ~10 km
away for every other shape. Helper `shape_issues(detour)` lets
shape-focused tests ignore start issues. New pins (break on purpose
when a fixture is added): `PLACED` (3 items -> node ID),
`NOT_NEAR_ROUTE` (4 Broad & Chestnut items on far routes),
`START_OUTCOMES` counts (placed 3, not near route 4, not in OSM 47,
segment 2, no start place 9). Mutation survivors are equivalents only
(dedupe of shapes used in both directions; a hard-coded `"bus"` feed,
since `find_gtfs_route` never returns rail; `near[0]` vs `(crossing,) =
near`). 1078 tests total.
Real run (scratch, not committed), `025344Z` / `121123Z`: reference
built in 0.7 s, matching ~1 s per snapshot. Placed 110 / 134; no start
place 14 / 15; segment 2 / 2; not in OSM 4 / 4; not within 500 m 5 / 6;
route not in GTFS 5 / 5; ambiguous 0 / 0 (same as the scratch lookup).
The mutation runner is now a scratch script taking a mutations file
(`MUTATIONS = [(old, new), ...]`) plus target and test paths.

## Rejoin point and skipped stretch (tier B, 2026-11-25)

- `place.find_rejoin_point(steps, ways, keys, lines)`: the crossing of
  the last two steps' streets within `REJOIN_RADIUS_M` (30 m, from real
  data: 66 at 0-15 m, next 62 m) of the **affected** shapes only;
  exactly one or `None`, never an issue. `split_shared_ways` matters: a
  short way would otherwise "cross itself" (a test pins it).
- `skipped.skipped_stretch(line, start, rejoin)` (shapely + pyproj,
  EPSG:2272): `None` when the start is over 500 m or the rejoin over
  30 m from the line, the rejoin isn't after the start along it, or the
  stretch is over 3x its ends' distance + 100 m (a hairpin test pins the
  slack's unit: metres, not feet). `notice._skipped` takes the first
  affected shape that gives one.
- `RouteMatch.rejoin_point` / `.skipped` default to `None` so old
  detours files read. Real `121123Z`: 65 rejoins, 51 stretches.
- Test data: a "Federal Street" way crosses the test 17th one block
  north of Washington, so a test path can rejoin away from its start.

## Penn Square names (tier C step 1, 2026-11-26)

- `STREET_TYPES` gains `square`/`sq`: alerts write `S Penn Sq`,
  `Rittenhouse Sq`; OSM `South Penn Square`, `West Rittenhouse Square`.
  Both sides split alike, so nothing that matched before stops matching.
- `alert_street_name(name)` (used by `street_matches`): an alert's
  one-letter first word `N`/`S`/`E`/`W` becomes the full direction when
  more words follow (`S Broad St` -> `south broad street`, a full-name
  match). Alert side only, like the OSM-only prefix drop: a lone letter
  is a letter street (`E St`).
- Real effect (`121123Z` / `141550Z`): no start point changed; +2
  rejoins and stretches (route 44 `Broad` -> `S Penn Sq`, route 96
  `W Fornance St` -> `Pine St`); the tier C walk measurement goes from 65
  to 80 walked paths on `121123Z` (39 on `141550Z`).
- Found while checking: a turn's left/right must be read over a
  distance, not from the two segments at the node: `South Penn Square`
  leaves 15th St almost straight south for ~45 m before curving east.
  Read 30-200 m out, all 185 checkable turns agree with the message.

## Walking a street (tier C step 2, 2026-11-26)

- networkx added (your choice over ~25 hand-written lines).
- `walk.street_graph(ways, selected)`: one street's ways as an
  undirected `nx.Graph` (no one-way tags in the cache; the message picks
  the streets). Nodes = OSM node IDs with `lon`/`lat`; edges = a way's
  consecutive nodes, `length_m` (equirectangular, mean latitude: a
  0.1-degree diagonal test pins both). `_metres_between` duplicates
  `crossings._metres_between`: a candidate for `geo.py`.
- `walk.walk_street(graph, sources, targets)`: `multi_source_dijkstra`
  by `length_m` from the sources on the street to the nearest target;
  a source that is a target -> one-node walk; `None` when nothing is on
  the street or reachable, or two targets tie exactly (a binary-exact
  test: lon -75.5 / -75.0 / -74.5). Weight by metres, not hops, is
  pinned (a 1-edge far target vs a 2-edge near one).
- `walk.turn_side(incoming, outgoing)` (step 3a): `"left"`/`"right"`
  from the cross product of the directions read over `TURN_LOOK_M`
  (100 m: the first point at least that far back / ahead, else the
  walk's end); `None` for a walk under 2 points (an empty one too: no
  IndexError) or exactly straight on. `Side` (not `Turn`: the model's
  has `"via"`). Tests rebuild the Penn Square corner (first segment says
  right, the turn is left) and pin the look distance at 99 / 101 m.
- `path.walk_turns(steps, sources, ways, keys)` (step 3b, new
  `match/path.py`, chaining like `place.py`): walks `steps[1:-1]`, each
  street from the corner it was turned onto at to its nearest crossing
  with the next (`walk_street` over every crossing's nodes); returns
  `(legs, corner)` (`Leg`: street as written, nodes, `(lon, lat)`
  points; `corner` = the last crossing's whole node group, where the
  last street starts) or `None`. Turns between legs must agree
  (`turn_side`; can't tell = accepted); the first turn (off the route)
  isn't checked there. Tests: a grid (17th/Broad x Washington/Reed),
  plus a slip road (a wide crossing: the next leg starts from its
  nearer node) and a diagonal Passyunk (a one-node leg).
- `path.walk_to_route(steps, corner, ways, keys, lines, rejoin_node)`
  (step 3c): the last street from `corner`. Known rejoin: the walk must
  end on it (usually a one-node leg: tier B's rejoin is the last two
  streets' crossing, i.e. the corner). None: to the nearest node within
  `REJOIN_RADIUS_M` of the affected lines (the extension you chose), but
  **no leg when the corner is itself that near** (decided from real
  data, `121123Z`: of 30 walks without a rejoin, 23 corners sit 89-462 m
  off the route, 6 within 30 m, 5 of those two-street paths like "via
  Harbison ave, Right on Frankford", where the message doesn't say where
  the bus gets back on). First tried "near nodes not connected to the
  corner through near nodes": wrong with sparse OSM nodes (two near
  nodes joined by a 111 m edge that leaves the route).
- `path.detour_path(steps, start, rejoin, ways, keys, lines)` (step
  3d): `walk_turns` + `walk_to_route` + the turn onto the last street;
  a tier B rejoin at the start counts as none; legs joined into one
  line (a shared corner once; a wide crossing's two nodes both kept);
  under 2 points -> `None` (pinned with a duplicate-position OSM node).
  Returns `DetourPath(line, rejoin)`. Real: `121123Z` 63 paths of 97
  candidates (41 on tier B's rejoin, 22 rejoins found by walking),
  71 m-5.2 km (median 2.1 km), 5,199 points; `141550Z` 36 of 48 (28 +
  8), 1,776 points.
- `RouteMatch.path` (step 4; model change): `match_notice` calls
  `notice._path` (needs a start point) with the affected shapes' lines;
  a path's rejoin replaces `rejoin_point` (the same point when tier B
  had one), then `_skipped` cuts from it. Test streets gain "South Mole
  Street" (a block east of 17th) for a round-the-block path; no fixture
  pin moved (fixture paths can't be walked on the test streets). Real:
  `121123Z` 63 paths, rejoins 67 -> 89, stretches 53 -> 75, detours file
  263 -> 423 KB; `141550Z` 36 paths, rejoins 39 -> 48, stretches 29 ->
  38.
