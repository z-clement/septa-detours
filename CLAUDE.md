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
- Direction names come from SEPTA's `directions.txt` (a non-standard GTFS
  extension, both feeds): `(route_id, direction_id)` -> `"Northbound"` etc.
  `direction_id` 0 means a different compass direction per route (route
  2: SB, 24: NB, 64: WB). A few bus routes say Inbound/Outbound/Loop; rail
  only Inbound/Outbound. The rail copy has CRLF line endings.
- The alerts API still uses pre-2025 route names in places (MFO/BSO,
  trolleys 10/11/13/15/34/36/101/102, MFL/BSL/NHSL; Bus Revolution H, L,
  R); GTFS uses the new ones. See `match/routes.py`.
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

Reached: **`match/` routes + directions are done**: parsed notices ->
`list[Detour]` via `match_notices(notices, routes, trips, directions)`,
with the GTFS route and every shape in the notice's direction. Before
that: `parse/` (snapshot bytes -> `list[DetourNotice]` via
`parse_snapshot`), and one route plotted with MapLibre. No geometry for
the detour itself yet, and nothing consumes `Detour` yet. See "Geography
plan" and "Next" at the end.

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

Done: second snapshot `2026-11-25T121123Z` (~9 h after the first, not a
day): 140 -> 166 detours. 5 removed, all already past their API `end`
(SEPTA removes promptly); 31 added, mostly Thanksgiving parade reroutes
for 11/26, posted ~14 h before they start (parse must not assume a
detour is active). No new direction spellings. Fixtures added:
`2026-11-25T121123Z__bus_route_31.json` and `__bus_route_124.json`; the
README now has one index table per snapshot. Findings:
- Same detour across snapshots: route 31 #2 is byte-identical in both
  route 31 fixtures (test `source_key` stability with it). Items 0-4 kept
  their indices; new items were appended (not guaranteed by SEPTA).
- Back-to-back phases: route 31 #3 ends 11/26 2:00 AM exactly when #5
  starts.
- Truncated LS `"Broad &"` (31 #6): not blank, so it's a known location
  and the notice can be `complete`. Open: flag in parse/ or leave to
  match/ (Claude leans match/).
- Doubled-dash date `"11-26--26"` pasted onto 7 routes; `"S PEnn Sq"`,
  `"Sping Garden"`; same place spelled `"30th & Chestnut Sts"` and
  `"30th & Chestnut"` (124 #0 vs #3).

Done: `parse/` skeleton (scaffolded by Claude at my request). Every function raises `NotImplementedError`; ruff,
ty and imports pass. Layout:
- `_api.py`: private raw models `ApiRoute` (`route_id`, `mode`,
  `detour`) / `ApiDetour` (the six strings), `extra="ignore"` (outside
  format; unlike `model.py`'s `forbid`), strict, frozen.
  `read_snapshot(content: bytes) -> list[ApiRoute]`: **done** (see
  below). A structural error fails the whole snapshot
  (`ValidationError`): API drift should be loud, not skipped.
- `text.py::clean_text(raw) -> str | None`: **done** (see below).
- `times.py::parse_api_datetime(raw) -> datetime` and
  `local_time_issue(moment) -> str | None`: **done** (see below).
- `direction.py`: `normalize_direction(token) -> Direction | None` and
  `find_directions(message) -> tuple[Direction, ...]`: **done** (see
  below). Finding is separate from deciding.
- `notice.py`: `make_source_key(route_id, location_start, start) -> str`,
  `parse_detour(route, detour, snapshot) -> DetourNotice`,
  `parse_snapshot(content, snapshot) -> list[DetourNotice]`: all
  **done** (see below).
Decisions:
- Field parsers raise `ValueError` with a reason; only `parse_detour`
  catches, turning it into `None` + an issue prefixed with the field name
  (`"start: ..."`). Messy text never raises out of `parse_detour`; bugs
  (e.g. a `CleanText` violation) still do.
- Directions: exactly one distinct -> it; none or 2+ different ->
  `None` + issue. Never pick one.
- `end` < `start` -> keep both, add an issue. API `start`/`end` win over
  times in the message text.
Open (in `parse_detour`'s docstring; still undecided, see "Next"):
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
Write NBSP in tests as `"\u00a0"` (RUF001).

Done: `parse/times.py`. `parse_api_datetime`: `clean_text` (blank ->
`ValueError("blank datetime '...'")`), then `strptime` with
`API_DATETIME_FORMAT = "%m/%d/%Y %I:%M %p"` (leading zeros optional, any
case of AM/PM; all 108 fixture values fit), then
`.replace(tzinfo=SEPTA_ZONE)`. Failure -> `ValueError("unrecognized
datetime '...'")` `from None`; messages quote `raw` as sent. Needs
`# noqa: DTZ007` (zone attached on the next line). Never
`naive.astimezone(zone)`: it reads naive as the *machine's* zone and
passes only on an Eastern machine (a `TZ=UTC` + `time.tzset()` test
guards it). `strptime` already treats a format space as `\s+`, so
`clean_text` is redundant there but kept to state the rule explicitly.
Decided DST (option C): accept, don't raise. `strptime` gives `fold=0`,
so a fall-back 1:xx reads as EDT; a spring-forward 2:xx keeps the
pre-change offset (= 3:xx EDT). Separate pure
`local_time_issue(moment) -> str | None` flags it: gap = wall time
changes on a UTC round trip (checked first, since in a gap flipping
`fold` also changes the offset, PEP 495); overlap = flipping `fold`
changes `utcoffset()`. Uses `moment.tzinfo` (fixed offsets never
flagged); naive -> `ValueError`. Messages: `"nonexistent local time
2027-03-14 02:30 (DST gap); read as 03:30 EDT"`, `"ambiguous local time
2027-11-07 01:30 (DST overlap); read as EDT"`. **`parse_detour` must call
it for start and end** and add the result (field-prefixed) to `issues`.
Python gotcha: aware datetimes with the *same* `tzinfo` compare by wall
time, ignoring offset and `fold`. Harmless now (we never make `fold=1`),
but `parse_detour`'s `end < start` check compares wall clocks; use
`.astimezone(UTC)` if that ever matters. `tests/test_times.py` (53);
20 mutations, 17 caught, 3 equivalent (cached `ZoneInfo` is the same
object; `raw.strip()` vs `clean_text`; `resolved != moment`). The
reusable mutation runner is a scratch script (not committed): copy the
file, apply `[old, new]` pairs that must each match once, run pytest
with `PYTHONDONTWRITEBYTECODE=1`, restore in `finally`. 256 tests total.

Done: `parse/direction.py`.
- `normalize_direction(token)`: lookup in `_SPELLINGS` (12 entries,
  written out one by one, keyed casefolded) on `token.casefold()`.
  Decided: **case ignored** (my choice). Each pattern covers all four
  directions: `NB`, `N/B`, `Northbound` (seen so far: `NB SB EB WB`,
  `W/B` once, `Eastbound`/`Westbound`). Nothing else forgiven: `"SB,"`,
  `" NB"`, `"Webster"`, `"N.B."`, `"W / B"`, `"inbound"` -> `None`.
  Stripping punctuation is the tokenizer's job.
- `find_directions(message)`: split on `_TOKEN_SEPARATOR =
  r"[^\w/]+"` (every char but letters, digits, `_`, `/`), normalize each
  token, dedupe in first-appearance order with `dict.fromkeys`. `/` stays
  inside tokens so `W/B` survives; dates and `Tower/Manor` become harmless
  tokens. Known gaps, safe (no direction -> issue later): `"NB/SB"` is one
  token (not seen; pinned by a test); a direction glued to digits or
  letters (`11:59pmSB`) isn't found.
On all 157 distinct real messages (both snapshots): 151 give one
direction, 6 give none (5 "Discontinued Transit Stop" + route 24 #1),
none give two different ones; ignoring case added no surprise matches.
`tests/test_direction.py` (78): spellings, case, rejections, a
fixture-driven `(stamp, route_id, index, expected)` table, hand-built
order/dedupe/punctuation cases. Mutations: 15 + 10; 2 survivors, both
equivalent (`.lower()` vs `.casefold()` on ASCII keys; dropping `+` from
the separator only adds empty tokens, which normalize to `None`).
334 tests total.

Done: `parse/notice.py::make_source_key`. Decided (my choice):
whitespace + case. Each field -> `(clean_text(raw) or "").casefold()`;
blank and whitespace-only both hash as `""`; inner runs collapse to one
space (not removed). Nothing else forgiven: `"3:00"` != `"03:00"`. The
three fields are hashed as `json.dumps([...])` (no separator character,
so text can't shift between fields and collide), UTF-8, `sha256`, first
`SOURCE_KEY_LENGTH = 16` hex chars. `tests/test_notice.py` (24) includes
a **pinned value** (`661b7024a25d2bbd` for route 31 #4): keys are compared
across snapshots parsed at different times, so changing the algorithm
must be deliberate. Route 31 items 0-4 get equal keys across both
snapshots (they're byte-identical, so the fixtures can't distinguish
normalizations; hand-built tests do). 15 mutations, 13 caught; 2
survivors only matter for non-ASCII input (none in fixture key fields):
`.lower()` vs `.casefold()`, `ensure_ascii=False`.

Done: `parse/_api.py::read_snapshot`: module-level
`_SNAPSHOT = TypeAdapter(Annotated[list[ApiRoute], Field(min_length=1)])`,
then `_SNAPSHOT.validate_json(content)`. Everything bad is a
`ValidationError`: invalid JSON, invalid UTF-8, a BOM, trailing garbage,
non-list top level, null/missing/wrong-type fields at either level.
Decided (my choice): **`[]` is rejected** (real snapshots list all ~185
routes, even detour-less ones; `[]` would read as "no detours anywhere");
**duplicate `route_id`s not checked** (not a shape problem; none seen).
Values are verbatim (the API's `\/` decodes to `/`; no cleaning).
Checked by hand: both real snapshots have 185 entries, no BOM, all six
detour keys present and all strings. `tests/test_api.py` (36): every
fixture wrapped as `b"[" + bytes + b"]"` and compared field by field to
the decoded JSON; `make_entry`/`make_detour(**overrides)` helpers; a
25-case rejection table. 11 mutations, 10 caught; `strict=False`
survives and is equivalent for JSON input (lax JSON mode doesn't coerce
numbers/bools/arrays to `str` or strings/objects to `tuple`). Strict
does bite in Python: `ApiRoute(**dict)` with a list of dicts fails, so
tests compare against `read_snapshot(...)` output instead. 394 tests
total.

Claude habit to watch: it has twice typed literal NBSPs into test
strings. Ruff RUF001 catches it; fix with `sed -i
's/\xc2\xa0/\\u00a0/g' <file>` (Edit can't match the invisible char).

Done: `parse/notice.py::parse_detour` and `parse_snapshot` (written by
Claude in four increments, each reviewed). `parse_detour`:
- `source` = `SourceText` with the raw strings verbatim; `source_key` =
  `make_source_key` on the *raw* `(route_id, location_start, start)`.
- `location_start`/`location_end`/`reason`: `clean_text`. Decided (my
  choice): blank -> `None` with **no issue** (a `None` location_start
  already makes `status` `unknown`; blank LE/reason are normal). So an
  `unknown` notice can have empty `issues`: consumers must check
  `status`, not just `issues`.
- Private `_parse_time(field, raw) -> (datetime | None, issues)`: catches
  `ValueError` -> `"start: unrecognized datetime '...'"` /
  `"end: blank datetime ''"` (the parser's message, field-prefixed); a
  parsed value keeps any `local_time_issue` as `"start: nonexistent
  local time ..."` / `"end: ambiguous local time ..."`.
- Private `_is_before(later, earlier)`: compares **instants**
  (`.astimezone(UTC)`), not wall clocks: in a DST gap they disagree
  (start 3/14/2027 2:30 AM = 07:30 UTC is after end 3:10 AM = 07:10 UTC).
  Strictly before only; equal start/end is not flagged. Issue: `"end:
  before start"`. Skipped if either time is `None`.
- Private `_pick_direction(message)`: one distinct -> it; none ->
  `"direction: none found in message"`; 2+ -> `"direction: conflicting
  SB, NB in message"` (message order). No real message conflicts yet.
- Issue order (documented): start, end, order check, direction.
`parse_snapshot` = `[parse_detour(route, d, snapshot) for route in
read_snapshot(content) for d in route.detour]`; catches nothing (a
structural `ValidationError` fails the whole snapshot).
Tests in `tests/test_notice.py`: helpers `load_route` (fixture ->
`ApiRoute` via wrapped `read_snapshot`), `parse_fixture_item`,
`make_api_detour(**overrides)`/`parse_made` (route 55 #0's raw strings;
used for bad times, DST, conflicts: no fixture has those), and
`mini_snapshot` (fixtures joined into one API list, deliberately
unsorted: 55, APP, 64, trolley 15, 24). Route 55 #0 is compared as one
whole hand-written notice. Fixture sweep: all **65** fixture items parse
and JSON round-trip; a pinned `NOT_COMPLETE` dict lists the 4
non-complete items (24 #1, 6 #0: partial, no direction; 64 #1, #2:
unknown, no issues); the other 61 are complete. **Adding a fixture
breaks the pin on purpose**: review its items, then update the count
and `NOT_COMPLETE`. Mutations: 19 + 14 + 10 + 5 (sweep) + 6, all caught
except equivalents (`directions[0]` vs `[-1]` when len is 1). Bad-time
handling is covered only by hand-built tests (the sweep can't see it).
428 tests total.
Real snapshots, by hand: `025344Z` 140 notices (131 complete, 7 partial,
2 unknown); `121123Z` 166 (157 / 7 / 2). Every partial is
"direction: none found"; every unknown is route 64's blank-LS items.
README "Expected" guesses held, except the ones that hinge on open
questions (recurrence / mismatch issues are not added, so route 2 #0,
32 #2, 44 #3 are `complete`). Route 24 has 4 items, not 3.

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

Done: `gtfs/load.py::load_directions` (`DIRECTION_COLUMNS`: `route_id`,
`direction_id` Int8 like trips, `direction`, `direction_destination`).
Missing file -> `FileNotFoundError` (loud if SEPTA drops the extension).
Every trips `(route, direction_id)` is covered; no duplicates.
`tests/test_load_directions.py` (10, the first direct loader tests; real
rows under `tmp_path`, incl. a CRLF rail file).

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
  first). Narrowing needs location (tier B below).
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

Geography plan (agreed; not started). 170 distinct real messages: 126
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
Open decisions (mine): street data, OSM (covers suburbs: routes 103, 124
leave the city; names need normalizing) vs City of Philadelphia
centerlines (closer names, city only); Claude leans OSM. Libraries:
shapely + pyproj, likely networkx (or heavier osmnx); not a routing
engine (it picks its own streets). Street-name matching: exact after
normalizing plus a small alias table from fixtures, not fuzzy ("Sping
Garden", "Graysferry", "Garney", "Broad &"). Each tier adds geometry to
`RouteMatch` -> a `model.py` change, flag first.

Next (clean session). Ask me which to do first:
1. **Get `Detour`s onto the map**: nothing consumes them yet. A
   `python -m septa_detours.match` command (snapshot -> `Detour` JSON in
   `data/processed/`), and/or `export/` GeoJSON of detoured routes
   (affected shapes, styled by direction) for `web/`.
2. **Tier A** of the geography plan (decide the street data source first
   if intersection lookup needs it; stop closures can use `stops.txt`).
3. **Settle parse's open questions** (each is my decision; ask):
   recurring windows ("7am - 4pm Mon thru Fri") and message-vs-API
   mismatches (route 44 #3, 61 #1): add an issue or not? Flagging makes
   many notices `partial` and changes the pinned `NOT_COMPLETE`.
   Detecting either means parsing message text, which `parse/` doesn't do
   yet. And a `kind` field (reroute / stop closure / relocation; route 6,
   9, BSO findings): changes `model.py`, so flag it first.
4. **Keep collecting snapshots** (`uv run python -m septa_detours.ingest`);
   run parse + match over each and add fixtures for new quirks (then
   update all the pins listed above).
Same way of working: small increments, tests from fixtures, mutation
checks, stop for my review after each.
