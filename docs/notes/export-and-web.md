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
