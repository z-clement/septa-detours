# SEPTA Detours

A tool that maps SEPTA service detours: it collects detour notices, turns them
into structured data, matches them to the transit network, and shows them on a map.

## How I want to work (read this first)

This is a learning project. I want to write most of the implementation myself.

- Default to **explaining, reviewing, and scaffolding**, not implementing.
- When I ask for a new module, give me a skeleton: file layout, function
  signatures, docstrings, and `TODO` markers. Do not fill in the bodies unless I say so.
- When I show you code, review it: point out bugs, edge cases, and design
  problems, and explain *why*. Suggest fixes in words or short snippets, not full rewrites.
- If I'm stuck, ask me a guiding question or give a hint before giving the answer.
- Only write full implementations when I explicitly say "write it" or "implement this".
- Don't make changes outside the file or function I'm working on. If you think
  something elsewhere should change, tell me instead.
- Ask before adding a new dependency.
- Go slowly, one task at a time. Explain the reasoning behind each step,
  and stop for me to check before moving to the next one.

## Architecture

Three stages. Each stage only talks to the next through the `Detour` model.
Never let one stage reach into another's internals.

1. **Ingest** (`src/septa_detours/ingest/`): fetch only. Save raw responses
   untouched to `data/raw/`. No parsing or interpretation here.
2. **Parse + match** (`parse/`, `match/`): turn raw text/alerts into structured
   fields (parse), then tie those to GTFS routes, stops, and shapes (match).
3. **Export + present** (`export/`, `web/`): write GeoJSON for the frontend and
   render it on a map.

The shared data type lives in `src/septa_detours/model.py`. If the `Detour`
model changes, flag it, since every stage depends on it.

## Repo layout

```
data/raw/        untouched downloads (gitignored)
data/gtfs/       SEPTA static GTFS (gitignored)
data/processed/  normalized detours (sample files may be committed)
src/septa_detours/{ingest,parse,match,export}/
src/septa_detours/gtfs/   shared GTFS reference data (not a stage): load.py
                          reads tables, shapes.py builds coordinate lists,
                          routes.py finds a route's shapes
src/septa_detours/model.py
web/             map frontend
tests/fixtures/  saved real alerts, including ugly/ambiguous ones
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
- Candidate libraries (ask before adding each): httpx (ingest),
  shapely + pyproj (match; project to EPSG:2272 before measuring distances)

## Commands

- Run tests: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format .`
- Fetch data: `uv run septa-detours fetch` (planned, not built yet)
- Serve the map: `python -m http.server -d web` (planned; export writes
  GeoJSON to `web/data/`)

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

Goal: load GTFS and plot one route with **MapLibre** (export the route as
GeoJSON to `web/data/`).

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

Next: a small script that loads GTFS and writes
`web/data/bus-21.geojson`, then the MapLibre page (`web/` doesn't exist
yet). Glue only: all logic already lives in `gtfs/` and `export/`.
Things to decide in that step:
- Where it lives: `scripts/export_route.py` (`uv run python ...`),
  `python -m septa_detours.export`, or a `[project.scripts]` CLI now
  (CLAUDE.md currently says to add the CLI with `fetch`).
- Hardcode route 21 or take `feed`/`route_id` arguments (argparse is
  stdlib, no new dependency).
- A known route with no shapes gives an empty FeatureCollection (unknown
  routes already raise in `route_properties`): write it, or error?
- Load only the needed feed (`load_trips(["bus"])`) to keep it fast.
- Paths are relative to the repo root (`DEFAULT_GTFS_ROOT`,
  `DEFAULT_WEB_DATA_DIR`), so run from there.

After that: collect raw alerts into `data/raw/`. The `Detour` model in
`model.py` is still deferred. Later, `match/` must map detour text like
"Route 21" / "the L" to `route_id` via `route_short_name` (not always
equal to `route_id`; check rail).
