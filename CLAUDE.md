# SEPTA Detours

A tool that maps SEPTA service detours: it collects detour notices, turns them
into structured data, matches them to the transit network, and shows them on a map.

## How I want to work (read this first)

This is a learning project. Claude may write the implementation, but
slowly and methodically, so I can follow and review every step.

- Work in small increments: one function (or one small group of tests) at
  a time. Don't write a whole module in one go.
- Before writing, say briefly what you're about to write and why, including
  any design decision it settles. If a decision is genuinely mine to make,
  ask first.
- After each increment: run the tests and lint, show me what changed,
  explain the reasoning and edge cases, then **stop for me to check before
  moving on**.
- Write tests alongside the code, driven by real fixtures, and
  mutation-check them (break the code, see the test fail).
- When I show you code I wrote, review it: point out bugs, edge cases, and
  design problems, and explain *why*.
- Don't make changes outside the file or function we're working on. If you
  think something elsewhere should change, tell me instead.
- Ask before adding a new dependency.

## Architecture

Three stages. Each stage only talks to the next through the shared models
in `model.py`: parse -> match through `DetourNotice`, stage 2 -> export
through `Detour`. Never let one stage reach into another's internals.

1. **Ingest** (`src/septa_detours/ingest/`): fetch only. Save raw responses
   untouched to `data/raw/`. No parsing or interpretation here.
2. **Parse + match** (`parse/`, `match/`): turn raw text/alerts into structured
   fields (parse), then tie those to GTFS routes, stops, and shapes (match).
3. **Export + present** (`export/`, `web/`): write GeoJSON for the frontend and
   render it on a map.

The shared data types live in `src/septa_detours/model.py`. If any model
there changes, flag it, since every stage depends on them.

## Repo layout

```
data/raw/        untouched downloads (gitignored); alerts/ holds API snapshots
data/gtfs/       SEPTA static GTFS (gitignored)
data/processed/  normalized detours (sample files may be committed)
src/septa_detours/{ingest,parse,match,export}/
src/septa_detours/gtfs/   shared GTFS reference data (not a stage): load.py
                          reads tables, shapes.py builds coordinate lists,
                          routes.py finds a route's shapes
src/septa_detours/io.py   shared helper (not a stage): write_bytes_atomic
src/septa_detours/model.py
web/             map frontend
tests/fixtures/  saved real alerts, including ugly/ambiguous ones;
                 alerts/ holds API route entries + an annotated README
notebooks/       exploration only, not production code
```

## Stack

- Backend: Python 3.13 (pinned in `.python-version`), managed with uv
- Frontend: MapLibre GL JS, plain JS, no build step. Keyless basemap
  (OpenFreeMap or Protomaps)
- Tests: pytest
- Formatting/linting: ruff (Python). No JS linter for now
- Type checking: ty (Astral), via the VS Code extension; editor interpreter
  must be `.venv/bin/python`
- GTFS tables: polars (added). Shapely/geometry stays out of polars; build
  it from plain coordinate lists in `match/`
- Models: pydantic v2 (added). Validates structure only; messy-text
  interpretation lives in pure functions in `parse/`, never in validators
- HTTP: httpx (added, ingest only). Tests use `httpx.MockTransport`; no
  test touches the network
- Candidate libraries (ask before adding each): shapely + pyproj (match;
  project to EPSG:2272 before measuring distances)

## Commands

- Run tests: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format .`
- Export a route's GeoJSON (from the repo root):
  `uv run python -m septa_detours.export bus 21` -> `web/data/bus-21.geojson`
- Fetch an alerts snapshot (from the repo root):
  `uv run python -m septa_detours.ingest` ->
  `data/raw/alerts/<UTC stamp>.json`. A `septa-detours fetch` CLI is
  planned but not built
- Serve the map: `python -m http.server -d web`, then open
  http://localhost:8000 (export the route first; it reads `web/data/`)

## Data notes

- Static GTFS joins: `routes` -> `trips` -> `shapes` (via `shape_id`) and
  `stop_times` -> `stops`. Remind me of this if I get tangled.
- Two feeds, stored flat: `data/gtfs/bus/*.txt` and `data/gtfs/rail/*.txt`.
  IDs are only unique within a feed, so every loaded frame carries a `feed`
  column; group/join on `(feed, id)`.
- Always read GTFS as strings (`infer_schema=False`), then cast known-numeric
  columns. Real traps: bus `route_id` mixes `124`/`L1`; rail `shape_id`s
  have leading zeros (`001005`) and appear as `538_406` deep in the file.
- The two feeds have different column sets; only shared columns are loaded.
- The "bus" feed also holds trolleys (route_type 0), metro (1, L1/B1), and
  trackless trolleys (11). Filter modes by `route_type`, not `feed`.
- Choose integer widths from the GTFS spec's legal range, not today's data
  (e.g. `shape_pt_sequence` is Int32). Lat/lon are Float64.
- GeoJSON coordinates are `[lon, lat]`; GTFS columns are lat, lon.
- Detour text is messy and inconsistent. Real examples go in `tests/fixtures/`
  and should drive parser design. Never "fix" a fixture to make a test pass.
- Treat unparseable or ambiguous detours as `unknown` rather than guessing.
  A wrong map is worse than an incomplete one.
- Never commit raw downloads or full GTFS files.

## Conventions

- Type hints on all public functions.
- Small, pure functions where possible, especially in `parse/` and `match/`,
  so they're easy to test against fixtures.
- Prefer clear names over comments; use docstrings for intent and edge cases.
- Commit small and often. I review diffs, so keep changes focused.

## Current focus

<!-- TODO: update as the project moves -->
Tooling set up: dev deps (pytest, ruff), strict ruff config, lint passing,
pytest `testpaths = ["tests"]`. No CLI entry point yet; add
`[project.scripts]` back when building `fetch`.

Goal now: **implement `parse/`** (raw alert snapshot -> `DetourNotice`),
driven by `tests/fixtures/alerts/`. Reached earlier: load GTFS and plot one
route with MapLibre (route GeoJSON in `web/data/`). See "Next" at the end.

Done: `gtfs/load.py`: `read_table` (all-string read, `""` -> null, `feed`
column, ValueError naming feed/table on a missing column), private
`_concat_feeds` helper, and `load_routes` / `load_trips` / `load_shapes`.
Empty `feeds` list is treated as a caller bug (no special handling).
`stops` and `stop_times` loaders deferred; `stop_times` (133 MB) should
use lazy `scan_csv`.

Done: `gtfs/shapes.py::shape_coordinates`: `group_by(feed, shape_id,
maintain_order=True)`, `concat_list(lon, lat).sort_by(shape_pt_sequence)`
inside the `agg` (chosen so ordering doesn't depend on input order).
Output `coordinates: List(List(Float64))`; groups in first-appearance order.
Docstring follow-ups pending: note the `maintain_order` guarantee; note
that duplicate `shape_pt_sequence` values are kept in arbitrary relative
order (known gap, not handled; candidate `xfail` test later).

Done: `tests/test_shapes.py`, 6 tests over hand-built frames via a
`make_shapes` helper (`(shape_id, lat, lon, seq, feed)` tuples, explicit
`SHAPES_SCHEMA` matching `load_shapes`, `orient="row"`: without it polars
guesses columns when row count == column count). Covers sorting, gaps,
`[lon, lat]` order, feed separation, first-appearance order, output
schema. Test-writing habits: realistic Philly coords (lon ~ -75) so
lat/lon swaps can't cancel out; compare whole outputs (`.rows()`,
`.schema`); break the code once to see each test fail. Known weakness:
the first-appearance test has only 2 groups, so a random group order
would pass ~50% of the time.

Done: `gtfs/routes.py::route_shape_ids(trips, feed, route_id)`: filters
trips to `(feed, route_id)`, drops null `shape_id`, returns distinct
`(feed, shape_id, direction_id)` rows in first-appearance order. Uses
`trips` only; `routes` isn't needed for the join. `direction_id` is kept
on purpose: detours can affect only one direction. So a shape used in
both directions appears twice, and null `direction_id` is its own row.
Unknown route and shapeless route both give an empty typed frame; the
caller decides if that's an error. Tests in `tests/test_routes.py` (12,
`make_trips` helper with `(route_id, direction_id, shape_id, feed)`
tuples, `TRIPS_SCHEMA` matching `load_trips`); each was checked against
deliberately broken versions of the function. Ruff SIM300 flags
`CONSTANT == value` asserts; put the module constant on the right.

Decided: start with **route 21** (bus feed, `route_id` "21", 660 trips,
2 shapes: `317337` dir 0, `317338` dir 1). Route 42 (8 shapes) is a good
second check. Reference lookups live in `gtfs/`; GeoJSON building
lives in `export/`.

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
<feed> <route_id>` (glue only). `_build_parser` (argparse, `feed`
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
Decisions:
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

Done: `io.py::write_bytes_atomic(content, path)` (written by Claude at my
request). The atomic temp-file-then-`replace` write moved out of
`export/write.py` so every stage can share it. It works on bytes: ingest
saves response bytes untouched, and `write_geojson` encodes its own UTF-8.
`<name>.tmp` is a fixed name (known limit: two concurrent writers to the
same path would collide; use `NamedTemporaryFile(dir=...)` if that ever
happens). `tests/test_io.py`; `test_write.py`'s atomicity test now
patches `Path.write_bytes`, and it still proves `write_geojson` goes
through the helper.

Done: alerts ingest (written by Claude at my request; awaiting my
review). Source: SEPTA JSON API `https://www3.septa.org/api/Alerts/index.php`
only (the old `get_alert_data.php` doesn't respond; GTFS-RT
`rtServiceAlerts.pb` exists but is deferred, since it needs protobuf).
`ingest/alerts.py`:
- `fetch_alerts(client) -> bytes`: checks only the HTTP envelope. Non-2xx
  -> `httpx.HTTPStatusError`. Media type not exactly `application/json`
  (params stripped, case-insensitive) or an empty body -> `ValueError`.
  Malformed JSON is still saved (parse/'s job). The body is never decoded.
- `snapshot_path(fetched_at, root=data/raw/alerts)`: pure,
  `%Y-%m-%dT%H%M%SZ.json` in UTC (local time is ambiguous at DST
  fall-back); a naive datetime -> `ValueError`. Same-second fetches
  overwrite (accepted).
- `save_alerts_snapshot(client, root, clock)`: the clock is read *after*
  the fetch; a failed fetch writes nothing (not even the directory).
- `make_client()`: UA `septa-detours/0.1` (no personal details), 30 s
  timeout, follows redirects.
- `ingest/__main__.py`: same pattern as the export command. `main(argv)`
  catches `httpx.HTTPError` and `ValueError` (exit 1, `error:` on stderr);
  anything else keeps its traceback; argparse errors exit 2.
Tests: `tests/test_ingest_alerts.py` (all via `MockTransport`; CLI tests
monkeypatch `__main__.make_client` and `chdir` to `tmp_path`). 21
mutations, all caught; the decode/re-encode mutation needed a test with
non-round-trippable bytes (invalid UTF-8, Latin-1). 150 tests total.
Verified on real data: a ~200 KB snapshot, byte-identical to `curl`.

Alerts API shape (observed 2026-11-24): a JSON list of ~185 per-route
entries with keys `route`, `route_id`, `route_name`, `mode`, flags
(`isdetour` "Y"/"N", `isadvisory` "Yes"/"No", ...), `last_updated`,
`advisory` (HTML), and `detour`: a list of `{location_start,
location_end, start, end, message, reason}`. That day: 57 routes, 140
detours (`isdetour` is "Y" exactly when the list is non-empty). API
`route_id` is unique within a snapshot. Quirks that matter for parse/match:
- API `route_id` is `bus_route_21` / `trolley_route_15`, not the GTFS
  `route_id` `21`. Trolley 15 has `mode: "Bus"`.
- `last_updated` is stale (2023) on every route; useless for change
  detection.
- `start`/`end` look like `"11/25/2026   3:00 PM"` (irregular spaces,
  local time, no zone).
- `message` is turn-by-turn shorthand with typos and abbreviations:
  `"3pn on 11/25/26 thru 2am ..., SB via 17th St, Left on Spring Garden
  St, Right on Broad St, ... Reg Rt"` (SB = southbound, Reg Rt = back on
  the regular route, "btwn"). `location_end` can be `""`.

Done: `model.py` (written by Claude at my request). All models share a
`_Frozen` base: `frozen=True, extra="forbid", strict=True`.
- `SourceText`: the nine raw API strings verbatim + snapshot file name
  (a name, not a path).
- `DetourNotice` (parse output): `source`, `source_key` (hash of
  normalized `(route_id, location_start, start)`; not an identity),
  `start`/`end: AwareDatetime | None`, cleaned `location_start`,
  `location_end`, `reason`, `direction`, `issues`. `None` = couldn't
  determine; the why goes in `issues`.
- `Detour` = `notice` + `match: RouteMatch | None` (None = match failed;
  no "not attempted" state) + its own match `issues`. `RouteMatch` has
  `feed`, GTFS `route_id`, `shapes: tuple[AffectedShape, ...]`
  (`shape_id`, `direction_id`). No detour path geometry yet.
Decisions:
- One API `detour` list entry = one `DetourNotice` (45 of 57 routes had
  several). The raw API shape is parse's private model, not in `model.py`.
- `status` is a plain `@property`, not `computed_field`: a computed field
  is dumped to JSON and `extra="forbid"` then rejects it on reload.
  `unknown` = no `location_start`, or neither `start` nor `end`;
  `complete` = start, end, location_start, direction all known and no
  issues (`location_end`/`reason` optional); else `partial`.
- `CleanText` (pattern `^\S(?:.*\S)?$`): parsed text must be stripped and
  non-empty; blank -> `None`. Inner whitespace is allowed.
- `Direction` = NB/SB/EB/WB only. Real messages also say "Eastbound",
  "W/B"; parse normalizes. No inbound/both seen.
- `direction_id` is strict `int` with `ge=0, le=1`, not `Literal[0, 1]`
  (Literal accepts `True` and `1.0` even in strict mode).
- `start`/`end` only need *a* zone; choosing America/New_York is parse's
  job, and so is flagging `end < start` as an issue.
Tests: `tests/test_model.py` (35; `make_notice(**overrides)` over a real
route 2 entry). 15 mutations, all caught. 185 tests total.

Done: alert fixtures (chosen by Claude at my request, approved by me).
`tests/fixtures/alerts/`: 18 route entries from snapshot
`2026-11-25T025344Z`, named `<snapshot stamp>__<api route_id>.json`
(provenance-based; quirks live in the README, not the name). One file =
one whole route entry with its full `detour` list; tests pick items by
index. Copied with `jq` and checked equal to the source entry: decoded
values are identical, only formatting differs (the API's `\/` becomes
`/`). `README.md` holds the copy command and an index: one row per
interesting detour item (route, index, what makes it ugly, *expected*
result guessed before the parser exists). Parse tests are built from
those rows; challenge the guesses when writing them. Coverage includes
`bus_route_55` (clean baseline), `APP` and `trolley_route_15` (no
detours), and the Owl buses `rr_route_mfo`/`rr_route_bso` (`rr_` IDs and
rail-named modes, but buses).
Findings from reading all 140 detours:
- Stop entries come in three kinds: closures (route 6), prose closures
  where LS is the *replacement* stop and LE the closed one (route 9), and
  relocations (BSO "Clothespin stop"). Strengthens the `kind` question.
- Message text can contradict API fields (route 44 #3 "until 11/23" vs
  API end 11/24; route 61 #1 5:30pm vs 5:00 PM).
- Recurring windows ("7am - 4pm Mon thru Fri", "Monday thru Wednesday,
  7:00PM to 5:00AM") are common; the model can't represent them.
- "Trips Only" scoping (route 24 "Gloria Dei", route 68 "Express")
  affects only some trips: a `match/` problem.
- Direction can be missing (24 #1), repeated (24 #0 "NB Via ... Recover
  NB On"), spelled out at the end ("..., Eastbound"), or after the time
  ("Until 12/31/26 11:59pm SB,"). LS and LE can both be blank (64 #1, #2).

Done: `parse/` skeleton (scaffolded by Claude at my request). Every function raises `NotImplementedError`; ruff,
ty and imports pass. Layout:
- `_api.py`: private raw models `ApiRoute` (`route_id`, `mode`,
  `detour`) / `ApiDetour` (the six strings), `extra="ignore"` (outside
  format; unlike `model.py`'s `forbid`), strict, frozen. Fields written;
  `read_snapshot(content: bytes) -> list[ApiRoute]` body is a TODO. A
  structural error fails the whole snapshot (`ValidationError`): API
  drift should be loud, not skipped.
- `text.py::clean_text(raw) -> str | None`: **done** (see below).
- `times.py::parse_api_datetime(raw) -> datetime`: fixed API format
  only, attach `SEPTA_ZONE` (stdlib `zoneinfo`, America/New_York);
  raises `ValueError` quoting `raw`.
- `direction.py`: `normalize_direction(token) -> Direction | None` and
  `find_directions(message) -> tuple[Direction, ...]` (distinct, in
  first-appearance order). Finding is separate from deciding.
- `notice.py`: `make_source_key(route_id, location_start, start) -> str`
  (hashlib), `parse_detour(route, detour, snapshot) -> DetourNotice`,
  `parse_snapshot(content, snapshot) -> list[DetourNotice]` (API order;
  routes without detours contribute nothing).
Decisions:
- Field parsers raise `ValueError` with a reason; only `parse_detour`
  catches, turning it into `None` + an issue prefixed with the field name
  (`"start: ..."`). Messy text never raises out of `parse_detour`; bugs
  (e.g. a `CleanText` violation) still do.
- Directions: exactly one distinct -> it; none or 2+ different ->
  `None` + issue. Never pick one.
- `end` < `start` -> keep both, add an issue. API `start`/`end` win over
  times in the message text.
Open (TODOs in the docstrings; decide while implementing):
- `parse_api_datetime`: DST fall-back (ambiguous, `zoneinfo` silently
  picks `fold=0`) and spring-forward (nonexistent, accepted silently):
  raise, or accept and note?
- `normalize_direction`: case handling (data shows `NB` and
  `Eastbound`); token splitting must keep `W/B` whole and must not read
  `WB` into a word like "Webster".
- `make_source_key`: normalization (case, whitespace) and separator.
- Whether recurring windows and message/API mismatches add an issue
  (adding one makes most notices `partial`).
- A `kind` field (reroute / stop closure / relocation) would change
  `model.py`: flag it before changing.

Done: `parse/text.py::clean_text` = `" ".join(raw.split()) or None`.
Decided: inner whitespace runs collapse to one space (typing slips in 9
fixture values; match/ compares street names; `SourceText` keeps the
original). No-arg `split()` covers all Unicode whitespace incl. NBSP,
the same set `CleanText`'s `\S` rejects, so output always validates.
Never raises. `tests/conftest.py` holds the fixture loaders (pytest
fixtures, since `tests/` has no `__init__.py`): `read_alert_fixture`
(full file name -> bytes) and `alert_fixture_names` (sorted `*.json`).
`tests/test_text.py` (18) includes a sweep validating every fixture
location/reason against the real `CleanText`; 8 mutations, all caught.
Write NBSP in tests as `" "` (RUF001). 203 tests total.

Next (clean session): Claude implements `parse/`, one function at a
time, with tests from the fixture index, stopping for my review after each.
Order: ~~`clean_text`~~ -> `parse_api_datetime` -> `normalize_direction` ->
`find_directions` -> `make_source_key` -> `_api.read_snapshot` ->
`parse_detour` -> `parse_snapshot`. Keep
collecting snapshots over several days. Later, `match/` must map API
route IDs and detour text ("Route 21", "the L") to GTFS `route_id` via
`route_short_name` (not always equal to `route_id`; check rail and the
Owl routes).
