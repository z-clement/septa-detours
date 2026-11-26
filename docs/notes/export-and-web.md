# Notes: export and the web map (`export/`, `web/`)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Route GeoJSON, the export command, the first MapLibre page, and the
detours-on-the-map work (match command, `export detours`, the
detours page). Next steps: `docs/web-plan.md`.

Done: `export/geojson.py` (pure, no I/O). Pipeline for one route:
`join_route_lines(route_shape_ids(...), shape_coordinates(...))` ->
`route_properties(routes, feed, route_id)` ->
`route_feature_collection(lines, props)` (calls `line_feature` per row).
GeoJSON shapes are `TypedDict`s (`LineString`, `Feature`,
`FeatureCollection`); `Properties = dict[str, str | int | None]`.
Decisions:
- `join_route_lines`: anti join first and raise `ValueError` naming any
  `(feed, shape_id)` with no coordinates (no silent drops); then left join
  with `validate="m:1"` (duplicate coords -> `ComputeError`) and
  `maintain_order="left"` (polars joins don't keep order by default).
  Explicit `select`s so extra columns can't leak into output.
- `route_properties`: exactly one `(feed, route_id)` match or `ValueError`
  (0 = unknown route, 2+ = broken data). Dict built field by field, so new
  `ROUTE_COLUMNS` don't leak into GeoJSON. Colors get `#` in Python via
  private `_css_color`; null or malformed -> `None` (frontend picks a
  fallback). All 181 real routes have valid 6-hex colors.
- Route metadata goes on *every feature's* properties: MapLibre styles
  from feature properties and ignores FeatureCollection extras.
- `line_feature`: raises on < 2 points (message includes properties);
  shallow-copies coordinates and properties.
- `route_feature_collection`: per-row `shape_id`/`direction_id` win over
  same-named `route_props` keys; null `direction_id` stays JSON `null`;
  empty input gives a valid empty collection (caller decides).
- A shape used in both directions gives two Features with identical
  geometry; the frontend must style/filter by `direction_id`.

Done: `export/write.py` (the only I/O in `export/`).
`route_geojson_path(feed, route_id, root=web/data)` ->
`web/data/<feed>-<route_id>.geojson`; pure; raises `ValueError` unless
`route_id` fullmatches `[A-Za-z0-9_-]+` (reject, don't sanitize: cleaning
could make two routes share a file). `.geojson` is served by `http.server`
as `application/geo+json`. `write_geojson(collection, path)`: serialize in
memory first (`allow_nan=False`, `ensure_ascii=False`, compact
separators, trailing newline, UTF-8), `mkdir(parents=True)`, then write
`<name>.tmp` beside the target and `Path.replace` it (atomic; temp file
removed on any failure, incl. Ctrl+C). `web/data/` is gitignored.

Done: tests. `tests/test_geojson.py` (39; helpers `make_route_shapes`,
`make_coordinates`, `make_lines`, `make_routes`) and `tests/test_write.py`
(30, all disk tests use `tmp_path`; atomicity proven by monkeypatching
`Path.write_text` to write half then raise). 87 tests total, all passing.
Every behaviour was mutation-checked (27 deliberate breakages, each
caught). Mutation-check gotcha: run with `PYTHONDONTWRITEBYTECODE=1`,
since a stale `.pyc` (same size, same second) silently tests the wrong
code. Ruff RUF001 flags literal en dashes; write it as `"\u2013"` in tests.

Verified by hand on real data: route 21 gives 2 features (`317337` dir 0,
284 pts; `317338` dir 1, 282 pts), `route_color` `#EF3340`, ~13 KB file.

Done: `export/__main__.py`, run as `python -m septa_detours.export
<feed> <route_id>` (glue only). **Since changed** (see "Done: detours on
the map"): now the `route` subcommand, and `main` also turns
`FileNotFoundError` into exit 1. The notes below are otherwise current. `_build_parser` (argparse, `feed`
limited by `choices=ALL_FEEDS`), `export_route(feed, route_id) -> Path`
(raises `ValueError`), `main(argv=None) -> int` (testable; when the real
CLI arrives with `fetch`, a subcommand can call it). Decisions:
- Loads only the requested feed. Checks run cheapest-first: path
  validation (no I/O) -> `routes` (unknown route) -> `trips` (no shapes)
  -> `shapes` (the big file). Real route 21 runs in ~0.45 s, so no
  semi-join prefilter of shapes.
- A known route with no shapes raises; nothing is written (an empty file
  would be a silently blank map). A failure leaves an earlier export intact.
- `main` catches only `ValueError` -> `error: ...` on stderr, exit 1;
  anything else is a bug and keeps its traceback. Success prints
  `wrote <path>` to stdout, exit 0. Bad arguments: argparse exits 2.
- `cast("Feed", args.feed)`: argparse attributes are `Any`; `choices`
  backs the cast at runtime. `print` needs `# noqa: T201`.

Done: `tests/test_export_main.py` (19). A `mini_gtfs` fixture writes a
fake bus feed (routes `21`, `NS` with no trips, `BROKEN` with a missing
shape) under `tmp_path` and `chdir`s there, so real default paths are
used; no rail folder, so loading the wrong feed crashes. Check order is
proven by deleting GTFS files the code shouldn't need yet. One
subprocess test covers `raise SystemExit(main())`. 17 mutations, all
caught. The `FileNotFoundError` test depends on polars' exception type
for a missing file. 106 tests total.

Done: MapLibre page, `web/index.html` + `web/map.js` (written by Claude
at my request, commented for reading; I'm less familiar with JS).
**Since replaced** by the detours map (see "Done: detours on the map");
these decisions carried over. Decisions:
- MapLibre **5.24.0** UMD from unpkg (global `maplibregl`), not v6: v6
  is ESM-only and loads a separate worker file, which browsers refuse
  cross-origin from a CDN. Moving to v6 means vendoring it into `web/`.
- Basemap: OpenFreeMap `positron` (light grey, so route colors stand out).
- `map.js` is an ES module. `main` awaits `Promise.all([map.once("load"),
  loadCollection(url)])`; `loadCollection` checks `response.ok` (fetch
  doesn't reject on 404) and its error names the export command.
  Errors show in the `#error` banner (hidden via CSS `:empty`).
- One line layer: `line-color` = `coalesce(get route_color, #555555)`;
  width and offset interpolate by zoom. Directions are separated by the
  *same* positive `line-offset`: opposite vertex order puts each on its
  own (right-hand) side of the street. Known gap: a shape shared by both
  directions has identical geometry and order, so it still overlaps.
- Click popup lists every feature under the cursor (route, direction,
  shape_id), via `setText`/`textContent`, never HTML.
- `collectionBounds` computes `[[w,s],[e,n]]` by hand (no turf); null
  for an empty collection -> error banner, no `fitBounds`.
- Verified in headless Firefox: page, JS and GeoJSON load, style loads,
  no error. Headless can't capture the WebGL canvas, so check the drawn
  lines by eye in a real browser.

Done: **detours on the map** (written by Claude in reviewed increments;
my choices: two commands, start points **and** the detoured routes'
lines, latest input by default). Each stage talks to the next only
through `Detour` JSON.
- `model.py` (an addition; no model changed): private
  `TypeAdapter(list[Detour])` behind `dump_detours(detours) -> bytes`
  (compact UTF-8 JSON + `\n`, input order) and `read_detours(content) ->
  list[Detour]` (`[]` valid: zero detours is a real state; anything else
  invalid -> `ValidationError`). Mutation lesson: `strict=False` is **not**
  equivalent here (unlike `read_snapshot`): lax JSON mode turns `"1"` into
  int 1 for `direction_id`; a test pins it.
- `match/__main__.py`: `find_latest_snapshot(root)` (fullmatch of the
  `ingest` stamp name, newest by name; none -> `FileNotFoundError` naming
  the ingest command), `detours_path(snapshot, root)` (pure;
  `detours-<stem>.json`, any snapshot name), `match_snapshot(snapshot) ->
  summary` (parse **first**, so a bad snapshot fails before ~1 s of
  loading; then the bus feed + street cache -> `build_match_reference` ->
  `match_notices` -> `write_bytes_atomic(dump_detours(...))`), `main`.
  Decided (mine): **one output file per snapshot** (history), gitignored.
  `DEFAULT_ALERTS_DIR` and the stamp pattern are duplicated from
  `ingest/alerts.py` on purpose; a test checks they agree (incl. a name
  made by `snapshot_path`).
- `export/geojson.py`: `Point` TypedDict; `Feature.geometry` is
  `LineString | Point`; `point_feature(position, properties)` (exactly 2
  numbers or `ValueError` naming the properties; copies both).
- `export/detours.py` (pure): `detour_properties(detour)` flattens one
  detour to strings/`None` (MapLibre stringifies nested values):
  `source_key`, `status`, `direction`, cleaned `location_start`/`_end`,
  `start`/`end` as ISO 8601 with the parsed offset, `reason`, raw API
  `message`, `issues` = parse then match issues joined with `"; "` (`None`
  if none). `detours_feature_collection(detours, routes, coordinates)`:
  **lines first, then points**. Lines: one per distinct `(feed, route_id,
  shape_id, direction_id)` over every **matched** detour (placed or not),
  first-appearance order, props = `route_properties` + `shape_id`,
  `direction_id` (null kept as its own line), `detour_count`; coordinates
  via `join_route_lines` (missing shape raises). Points: one per placed
  detour, props = route + detour + `node_id`. A route missing from
  `routes.txt` raises even if nothing would be drawn (detours and GTFS
  disagree: loud).
- `export/__main__.py`: subcommands (decided: mine) `route <feed>
  <route_id>` (kept as a debugging tool) and `detours [file]`.
  `find_latest_detours(root)` matches `detours-<stamp>.json` exactly
  (`detours-mine.json` only when passed explicitly); constants duplicated
  from `match/`, checked by a test. `export_detours(file, path)` loads GTFS
  **only for the feeds used** (none if nothing matched: loaders treat an
  empty feed list as a bug, so it writes an empty collection directly);
  unlike `export_route`, an **empty collection is written** (a true
  state). Decided (mine): `main` catches `(FileNotFoundError, ValueError)`
  for **both** subcommands, like `match`/`streets`. The old `export bus
  21` form exits 2.
- `web/` (decided: mine) **replaces** the single-route page. One source,
  two layers split by `["geometry-type"]`: lines (as before) then circles
  (route color, white outline) on top. **One map-level click handler**
  (`queryRenderedFeatures`; start points win over lines, so one click =
  one popup). MapLibre **drops null properties** from clicked features,
  so popup code uses `??` fallbacks. Times shown with `timeZone:
  "America/New_York"`. `#status` line (bottom-left) counts what's in the
  file; empty data is a status, not an error. Popup CSS `white-space:
  pre-line` (the old page lacked it). A missing data file names `match`
  + `export detours`.
Tests: `test_match_main.py` (fake repo: route 2 GTFS, a two-way street
cache, a snapshot of route 2 + APP + route 55 fixtures -> 6 detours, 5
matched, 1 placed), `test_model.py`, `test_geojson.py`,
`test_export_detours.py`, `test_export_main.py`. Every increment
mutation-checked; survivors fixed with a test or documented as
equivalent. Gaps the checks found: two lines' coordinates swapped
unnoticed (tests compared props only); equal line/point counts hid a
swapped summary. JS checked by running `map.js`'s pure functions in Node
(scratch, not committed) on the real file under `TZ=UTC`; the drawn map
is checked by eye. 1203 tests total. ty: 45 pre-existing diagnostics
(the `**dict` test helpers; invariant `dict` vs `Properties`): don't add
more (annotate `Properties`, or type test helpers `Any`).

Done (2026-11-25): **`export/simplify.py`** (web plan P1-P2; pure, on
`[lon, lat]` lines; written by Claude in reviewed increments). Shared
geometry moved first (my choice): `distance_to_line_m`,
`EARTH_RADIUS_M` and now-public `distance_to_segment` live in
`septa_detours/geo.py` (not a stage), so export never imports `match/`.
- `simplify_line(line, tolerance_m)`: Douglas-Peucker. Projects once to
  flat metres from the first point, scaled at the line's **mean**
  latitude. Distance to the *segment*, not the infinite line, so a loop
  (first == last point) keeps its far side. A stack, not recursion (long
  shapes). Kept only if **more than** the tolerance off (a repeated point
  at tolerance 0 is dropped); a tie for farthest splits at the earlier
  point. Endpoints always kept; < 2 points or a negative/NaN tolerance
  -> `ValueError`; returns new lists.
- `round_line(line, decimals)`: rounds, drops a point equal to the one
  before it (decided: mine), a line that collapses to one position comes
  back as two separate copies (still a valid LineString). Use after
  simplifying. Real data: after simplifying at 2 or 5 m it drops nothing
  (points are already > 1 m apart) and saves only ~7% of JSON; on raw
  shapes it drops 788 of 532k points.
- `covering_shapes(lines, tolerance_m=20)`: the overview's shapes for one
  route-direction. Longest (metres) first, ties in input order; drop a
  shape when **every point is within the tolerance of any kept shape**
  (decided: mine, over "one kept shape covers it all": also drops shapes
  stitched from kept branches). Checks points only, so pass 2 m-simplified
  lines. Each kept shape gets a bounding box widened by the tolerance
  (east-west margin sized at the box's highest latitude, so it's never
  too small); the box is only a speed-up.
- Real data (all 1,009 shapes, 532k points): simplify keeps 21% of points
  at 2 m, 12.5% at 5 m, 9% at 10 m, ~2.2 s each; route 21's 284-point
  shapes -> 21 points at 5 m. Covering on 2 m lines: 593 of 1,006 shapes
  in ~4.4 s (200 route-directions need 1, 141 need 2+, max 8; route 14
  dir 0: 20 -> 6). The first attempt, comparing **raw** shapes, took
  108 s (the "one shape" rule: 629 kept); running two of those at once
  crashed the machine. Run real-data scratch scripts one at a time,
  `nice -n 19`, `POLARS_MAX_THREADS=2`, with a `timeout`.
Tests: `tests/test_simplify.py` (53; hand-built lines near 17th &
Washington), `tests/test_geo.py` (the moved distance tests). Mutation
checks: every survivor fixed with a test except `simplify_line`'s y
projection using `origin_lon` (a translation: equivalent) and two parts
of the box margin (`+ lat_margin` in the latitude it's sized at, and
`abs()`), which change the box by ~40 micrometres: correct, kept, too
small to test. 1256 tests total.

Done (2026-11-25): **the data contract** (web plan P3-P5; written by
Claude in reviewed increments). Decisions mine unless noted.
- `export/contract.py`: TypedDicts for every file the page reads
  (`Status`, `RouteEntry`, `RouteDetail`, `DirectionEntry`,
  `DetourObject`, ...), `SCHEMA_VERSION = 1`, `Mode`, `Timing`, `Bounds`.
  GeoJSON files reuse `geojson.FeatureCollection`; their property names
  are tuples (`NETWORK_PROPERTIES`, `START_PROPERTIES`,
  `SHAPE_PROPERTIES`), not TypedDicts, because `Properties` is a plain
  `dict` and ty can't match a TypedDict to it. `short_name` is always a
  string (falls back to `route_id`); `Status.gtfs` is `feed_version` or
  `None`.
- `export/site.py` (pure builders):
  - `MODE_ORDER` metro, trolley, trackless, bus, rail (D8); `route_mode`
    (unknown `route_type` raises); `route_sort_key`: mode, then all-digit
    names by value, then the rest ignoring case, then exact name.
    `[0-9]`, not `\d` (which takes any Unicode digit, e.g. `٣`).
  - `route_key` (`bus-21`; same safe-ID rule as `write.py`, a test checks
    they agree), `lines_bounds`.
  - `route_catalog` -> `routes.json`: shapeless routes listed with
    `has_shapes: false`, `bounds: null` (D4); detour counts per route;
    duplicates, unknown routes in bounds/detours raise. Colors via
    `geojson._css_color` (private, same stage).
  - `detour_object(detour)`: no `key` argument (it derives `route`: the
    key when matched, the API route ID when not); `direction_id` only when
    all matched shapes agree; `issues` a list.
  - `route_shapes` (trip counts, 2 m lines rounded to 5 decimals,
    `covering` per direction; order: direction, covering first, most
    trips, `shape_id`; `group_by(maintain_order=True)` so it never
    depends on polars' order), `route_directions` (`directions.txt` rows
    plus any drawn direction the file lacks), `route_detail`.
  - `network_collection`: covering shapes simplified at 5 m from the
    **raw** lines (not the 2 m ones, so errors don't add up).
  - `detour_timing(start, end, now)`: inclusive start/end; missing time
    or end before start -> `unknown`; naive `now` raises. The page needs
    the same rule in JS. `starts_collection`: exact start nodes (not
    rounded), timing at export time.
  - `status`: `generated_at` UTC with `Z`; `snapshot_fetched_at` from an
    ingest-style name (pattern duplicated, checked against
    `snapshot_path`; `strptime` alone would accept `2026-1-25...`).
  - Constants (D2, "for now"): `DETAIL_TOLERANCE_M = 2`,
    `OVERVIEW_TOLERANCE_M = 5`, `COVERING_TOLERANCE_M = 20`,
    `COORDINATE_DECIMALS = 5`.
- Real data (GTFS `v202611220`, snapshot `121123Z`): 181 routes (6
  shapeless), `routes.json` ~49 KB; 1,006 route shapes, 593 covering
  (~7 s to prepare); `network.geojson` 593 lines, 42k points, 0.97 MB;
  route details: bus-2 10 KB, bus-14 109 KB (the largest); 134 start
  dots, ~25 KB (84 active, 50 upcoming at snapshot time); `status.json`
  3 KB. Unmatched: 5 (H x2, L x2, R); route 68's "EB" items are
  matched with no shapes (the plan had this wrong).
- Tests: `tests/test_site.py` (hand-built frames, real route 2/68/mfo
  notices, real direction rows). Mutation lessons: test data that is
  *exactly* on a line hides tolerance bugs (move points ~1 m off); an
  unmatched detour last in a list hides `continue` -> `break`; a tie
  in sort order can pass by luck of polars' ordering (test both input
  orders); a message with no outer spaces can't show it's verbatim
  (`rr_route_mfo` #1 has trailing spaces). Survivors judged equivalent:
  `colors.get` after a membership check, `match` vs `fullmatch` before
  `strptime`. 1422 tests total.

Done (2026-11-25): **writing the contract** (web plan P6). D3 decided
(mine): **plain overwrite**, no history; `contract.py` lost
`CurrentPointer` and the `builds/` layout.
- `export/write.py::write_site(files, root)`: checks every path first
  (only `SITE_FILES` and `routes/<bus|rail>-<id>.json`, so nothing lands
  outside `web/data/`), encodes everything in memory (a NaN anywhere
  writes nothing), writes each atomically with route files first and
  `status.json` last, then deletes stale route files (regular files with
  a route-file name not written now; nothing else). A failure part-way
  leaves a mix of old and new (accepted) and deletes nothing. The JSON
  encoding moved into `_encode_json`, shared with `write_geojson`.
- `export/__main__.py`: `export site [detours.json]` ->
  `export_site(detours_file, root, now=None)`: detours read first (a bad
  file fails before GTFS), both feeds loaded, every builder run, all
  files written. **Every catalog route gets a detail file** (mine: the
  page never asks for a missing one). `_feed_versions`: `null` for a
  feed without `feed_info.txt`.
- Real run (`121123Z`, GTFS `v202611220`): ~9 s, ~350 MB RAM; 185 files,
  3.6 MB: `network.geojson` 970 KB, `routes.json` 48 KB, `starts.geojson`
  25 KB, `status.json` 3 KB, `routes/` 181 files, 2.5 MB (largest bus-14
  109 KB, bus-93 81 KB, bus-130 76 KB). The page will load ~1.05 MB up
  front.
- Tests: `tests/test_write.py` (+21; the path check's gaps found by
  mutation: an unescaped `.`, `match` vs `fullmatch`, the folder check),
  `tests/test_export_site.py` (13; a fake two-feed GTFS with no rail
  `feed_info.txt`, real route 2 notices on fake route 21). 1456 tests.

Done (2026-11-25): **W1, `map.js` split into modules** (no visible change
except plurals). `web/js/`: `format.js` (pure: `formatTime`,
`describeStart`, `describeLine`, `summarize`, new `plural`), `data.js`
(`loadCollection`, `loadDetours`), `mapview.js` (the only `maplibregl`
user: `createMap`, layers, popups, `collectionBounds`), `main.js`
(bootstrap, status/error). `css/app.css` from `index.html`'s `<style>`.
Modules with nothing to hold yet (`state`, `sidebar`, `routes`,
`detours`) come with W3/W4. Fixed: "1 detour start points on 1 routes"
and "detour(s)" -> `plural`, with the verb ("1 detour lists"). `formatTime`
also treats `null` as unknown (plain JSON in W2 keeps nulls; `new
Date(null)` is 1970). Tests: `web/test/format.test.js` (14, Node's
built-in runner, no npm; a real route 2 start point). Mutation lesson:
this machine is on New York time, so deleting `timeZone` passed until
the test file set `process.env.TZ = "Asia/Tokyo"`. No-visible-change
check: a scratch Node script ran the old `map.js` and the new `main.js`
with a fake `maplibregl`/`document`/`fetch` on the real
`detours.geojson`; the recorded calls, status and error text were
identical.

Fixed (2026-11-25): `export site` wrote the *detours file's* name
(`detours-2026-11-25T121123Z.json`) as `status.json`'s `snapshot`, so
`snapshot_fetched_at` was null; a test had pinned the wrong values. Found
by writing the page's status line against the real file. Now
`_snapshot_name` takes it from the detours (`notice.source.snapshot`;
several snapshots in one file raise), or, with no detours, from the file
name minus `match`'s `detours-` prefix. Lesson: check exported values
against what they *mean*, not just what the code produced.

Done (2026-11-25): **W2, the page draws the data contract.** `data.js`:
`loadSite()` (status.json first, alone, schema-checked, then routes,
network, starts in parallel), `routeDetailLoader()` (one fetch per route
file, failures retried). `format.js`: `routeLabel`, `statusLine` (zero
parts left out; a hand-named snapshot shows its name), `describeDetour`
(detour objects: explicit nulls, `issues` a list), `describeRoute`.
`routes.js` (pure): `detouredRoutes`/`detouredKeys` (any matched detour,
placed or not), `routesBounds`. `mapview.js`: grey network (D8, mine),
detoured routes in color on top (55 routes), start dots by export-time
`timing` (active solid, upcoming hollow, ended grey); a dot popup fetches
its route file (Loading... then the detour), a line popup lists each
route under the click once. Zoom: detoured routes' bounds, else the
whole network. Removed (D7, mine): `export detours`, `export/detours.py`
and their tests; the old page code. Checked with a scratch Node smoke
test (fake `maplibregl`/`document`/`fetch` on the real `web/data/`:
loads, layers, dot/line clicks, a stale schema) and by eye. Tests: 31
JS (`format`, `data`, `routes`).

Done (2026-11-25): **W3 step 1, `routes.json` windows (schema 2).** The
sidebar's "Detoured now" needs every matched detour's timing, but the
overview files had it only for placed detours (`starts.geojson`); 27 of
`121123Z`'s 161 matched detours aren't placed. Options were windows in
`routes.json`, placed-only timing, or no timing in the list; windows
chosen (mine). `RouteDetourCounts.windows`: one `[start, end]` per matched
detour, placed or not, snapshot order, ISO 8601 via `_iso` (shared with
`detour_object`, so the formats can't drift). `route_catalog` now counts
straight into each entry (the two Counters are gone). `SCHEMA_VERSION` 1
-> 2 in `contract.py` and `data.js` (mine): the contract's rule only
covered an old page reading new data; it now also bumps when the page
starts relying on a field, since old data would read silently wrong. The
JS stale-schema tests now use the real cases: data at 1 (stale data) and
a route file at 3 (stale page). Also decided: D4 (shapeless routes
listed greyed), D5 ("Not on the map" section). Real: 161 windows, none
with a missing time, `routes.json` ~60 KB. Mutation check: start/end
swapped, reversed order, placed-only windows, end = start, UTC
conversion, `""` for `None`, either version number reverted: all caught.

Done (2026-11-25): **W3 step 2, the sidebar's pure logic** (no DOM yet).
- `detours.js` `detourTiming(start, end, now)`: Python's `detour_timing`
  rule (inclusive ends; `unknown` for a missing time or end < start),
  plus one JS-only case: an unparseable time is `unknown`. Takes the two
  times, not a detour, so it serves both windows and detour objects. A
  `parseTime` helper was dropped: `Date.parse` already gives NaN for
  `null`/`undefined` (unlike `new Date(null)`, 1970), so the helper was
  untestable. Mutation lesson: deleting the `instanceof Date` check
  survived, since a string `now` still threw a `TypeError` (the engine's
  "getTime is not a function"); the test now checks our message and
  passes a fake with its own `getTime`.
- `routes.js`: `timingCounts(route, now)` (the four timings, adding up to
  `total`), `detouredNow(routes, now)` (`[{route, active}]`, most active
  first, ties in catalog order via stable `sort`). Real, at snapshot
  time: 49 of 55 detoured routes are detoured now (64 leads with 6). Test
  data: route 2's 7 real windows at 14:00Z split 2/4/1 (unequal counts).
- `groupByMode(routes)`: groups by first appearance, so JS doesn't repeat
  Python's mode order. Real: metro 5, trolley 8, trackless 3, bus 152,
  rail 13. An equivalent survivor: `Map.set` on an existing key keeps its
  insertion place (checked in Node, not assumed).
- `format.js` `modeLabel` (Metro, Trolleys, Trackless Trolleys, Buses,
  Regional Rail; unknown -> itself, via `Object.hasOwn` so "toString"
  isn't a prototype method).
- `searchRoutes(routes, query)` (the user's rule: a number matches only
  at the start). First built with numbers matching the start of *either*
  name; the real catalog showed `2` finding route 5 ("2nd-Market...")
  and `69` finding nothing (long names hold "69th St TC" mid-name), so
  numbers now match `short_name` only. Equivalent survivor: the blank
  query branch (`includes("")` is always true); kept as stated intent.
Tests: 60 JS (`format`, `data`, `routes`, `detours`). Suggested, not
done: Python's `detour_timing` docstring could name `web/js/detours.js`.

Done (2026-11-25): **W3 step 3, the sidebar DOM** (W3 complete). Decided
(mine): (a) a fixed 320 px left panel, the map the rest, the status line
at the top of the panel (rejected: a floating panel); (b) mode chips
toggle (all on at start), AND the search, greyed (not hidden) when the
search alone has none of their mode, sidebar only (the map isn't
filtered); (c) state in `main.js` until `state.js` (W4), `now` refreshed
every 60 s; (d) rows are `<button>`s with `data-key`, no click handler
yet. Also mine: row counts by timing ("3 now, 4 later") rather than a
total; search ranking (below); "Not on the map" only in the unfiltered
list.
- Layout: `body` a flex row; `#sidebar` a column (status, search, chips,
  then `#route-list`, the only part that scrolls; it needs
  `min-height: 0` or it grows past the window). Section headings
  `position: sticky`.
- `sidebar.js` (DOM only, no tests: `node --test` has no DOM; checked by
  eye): `renderRouteList(container, {routes, now, modeOrder, emptyText,
  unmatched})` rebuilds the list whole each call (181 rows is cheap);
  `createModeChips(container, modeOrder, onToggle)` builds the chips
  once and returns `update(on, available)`, so a chip toggled from the
  keyboard keeps its focus (a rebuild would drop it). Text only via
  `textContent`. Null `color`/`text_color` fall back in CSS (`#555` on
  white), so `sidebar.js` doesn't copy `mapview.js`'s `FALLBACK_COLOR`.
- `format.js`: `timingSummary(counts)` (zero parts left out, `""` for
  none), `TIMING_WORDS` (frozen; shared by rows and unmatched items),
  `apiRouteName` (`bus_route_L` -> `L`, `rr_route_mfo` -> `MFO`, unknown
  ids unchanged), `unmatchedSummary` ("Route L, NB: A to B"; missing
  halves dropped, "location not given").
- `routes.js`: `visibleRoutes(routes, query, modes)` (search AND modes);
  `searchRoutes` ranks text matches whose `short_name` starts with the
  query first (`k` had route K 58th of 62 matches, behind "Frankford",
  "Park", "Dock"); `groupByMode(routes, modeOrder = [])` so ranking
  reorders routes within groups, never the groups (mine; rejected: the
  best match's group moving to the top). `main.js` takes `modeOrder` once
  from the whole catalog.
- Real (`121123Z`, viewed Nov 25 evening): 52 routes detoured now (49
  "6 now, 2 later" first); greyed rows D1 Bus, D2 Bus, MANN, NOR Bus,
  T Bus, WTR Bus; `market` greys Trolleys/Trackless/Rail; the 5 unmatched
  are routes L x2, R (now) and H x2 (ended); H NB really is "Mt Pleasant
  & Creshem to Mt Pleasant & Creshem" in the API text.
- Mutation checks: all caught except one true equivalent
  (`TIMING_WORDS.ended` -> the literal `"ended"`). Patterns must be
  unique: `.join(", ")` appears twice in `format.js`.
- Known gaps: the per-minute rebuild closes any opened "Not on the map"
  `<details>` and drops keyboard focus inside the list (fix with W4's
  state, e.g. remember open `source_key`s); "Detoured now" is long (52
  rows): revisit if it feels so in use.
Tests: 81 JS.

## W4: focus a route (2026-11-25)

Decided first (yours): D6 ended detours in a collapsed "Ended (n)" group
at the bottom; the focused map dims the rest (network 0.6 -> 0.3 opacity,
other routes' colored lines and dots hidden); the route panel replaces
search, chips and list (status line stays); unplaced cards stay in their
group with a muted "Location not found on the map". Committed at each
step without review (allowed for this session).

- `state.js` (pure, tested): `createState({modes, now})` -> `get`,
  `subscribe(listener(state, changed))` (returns unsubscribe), actions
  `focus(key, detour = null)`, `setSearch`, `toggleMode`, `setNow`.
  Snapshots frozen; `toggleMode` makes a new Set; no-op actions notify
  no one (`setNow` compares times, not Date objects); `focus` to another
  route (or null) drops the selection. `parseHash`/`formatHash`:
  `#route=bus-21&detour=...`; empty values and a detour without a route
  parse as null; round-trips values that need encoding.
- `detours.js`: `TIMING_ORDER` (active, upcoming, unknown, ended) and
  `groupByTiming(detours, now)` (empty groups dropped, snapshot order
  within).
- `format.js`: `detourPlaces` (pulled out of `unmatchedSummary`; a
  same-place start/end is said once: 29 real stop closures read "Market
  & Schuylkill Ave to Market & Schuylkill Ave"), `directionLabel`
  (route's name via `direction_id`, else the API text "EB", else null;
  the contract's direction `name` may be null, none today in 353),
  `directionSummary` ("Southbound to 20th-Johnston", "Direction 0"),
  `detourHeadline`, `timingHeading` ("In effect (2)", "Upcoming",
  "Dates unknown", "Ended"; wording mine).
- `sidebar.js`: `renderRoutePanel(container, {route, detail, error, now,
  selectedDetour, onBack})`: header (Back, badge, names, directions),
  loading/error/no-detours notes, cards (`data-source-key`, `.selected`;
  parse issues in a closed "Parser notes" `<details>`). "Ended" stays
  open across re-renders of the same route. `routeBadge` shared with
  rows. `renderRouteList` now keeps opened unmatched items and keyboard
  focus across rebuilds (`focusSelector`: a row by section + key, since
  a route can be in "Detoured now" and its group; a summary by detour):
  the W3 gaps, fixed.
- `index.html`: `#browse` (search, chips, list) and `#route-panel`, one
  `hidden`; `[hidden] { display: none !important }` because
  `#browse { display: flex }` would otherwise beat the attribute.
- `mapview.js`: `addOverviewLayers` adds a `focus` source/layer (between
  detoured lines and dots; covering shapes 6 px at z16, others 3) and
  returns `showFocus({key, detail} | null)`. While the detail loads, the
  route's network lines stay colored (detoured layer filtered to the
  key); once loaded, the detoured layer is hidden. `fitRoute` is separate
  so only a focus change moves the camera; Back doesn't move it (mine).
  `addPopups` became `addClickHandler(map, routes, loadDetail, onFocus)`:
  one route under the click focuses it (a dot also selects its detour);
  several keep the old popup until W5's chooser. Lines are queried on
  the network layer only (focus features carry no `key`).
- `main.js`: one store; focus pushes a history entry (Back leaves the
  route), a selection on the same route replaces it; `hashchange` and
  `popstate` both read the hash (the second is a no-op); a hash naming
  an unknown route is the overview. The list renders only while shown;
  a detail load that finishes after the user moved on is dropped.
- Checking: headless Firefox (`firefox --headless --screenshot`) has no
  WebGL, so the map never loads; the sidebar DOM was checked with a
  scratch harness page (real data embedded as a static module import, so
  it renders before the screenshot's `load`). The map side (focus
  styling, clicks, Back) still needs a look in a real browser.
Tests: 107 JS.
