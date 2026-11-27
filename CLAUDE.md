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
data/raw/        untouched downloads (gitignored); alerts/ holds API snapshots,
                 osm/ holds Geofabrik extracts (<region>-<YYMMDD>.osm.pbf)
data/gtfs/       SEPTA static GTFS (gitignored)
data/processed/  pipeline output (gitignored; sample_* files may be
                 committed): detours-<snapshot stamp>.json = match output
                 (one per snapshot); streets.parquet = the street cache
src/septa_detours/{ingest,parse,match,export}/
src/septa_detours/gtfs/   shared GTFS reference data (not a stage): load.py
                          reads tables, shapes.py builds coordinate lists,
                          routes.py finds a route's shapes
src/septa_detours/streets/  shared OSM street reference data (not a stage):
                          load.py reads extracts, cache.py builds/reads the
                          Parquet cache; never imports from a stage
src/septa_detours/io.py   shared helper (not a stage): write_bytes_atomic,
                          write_chunks_atomic
src/septa_detours/geo.py  shared helper (not a stage): EARTH_RADIUS_M,
                          metres_between, distance_to_line_m
                          (equirectangular metres)
src/septa_detours/model.py
web/             map frontend (the detours map): index.html, css/app.css,
                 js/ (ES modules: main, data, mapview = the only
                 maplibregl user, sidebar = the sidebar DOM; format,
                 routes, detours, state, sheet = pure),
                 dom = shared DOM helpers, test/
                 (node --test); web/data/ holds the data contract
                 (`export site`; gitignored)
tests/fixtures/  saved real alerts, including ugly/ambiguous ones;
                 alerts/ holds API route entries + an annotated README
notebooks/       exploration only, not production code
docs/            plans (ui-plan.md = current, web-plan.md, geography-plan.md,
                 backlog.md) and notes/ (detailed per-area history)
```

## Stack

- Backend: Python 3.13 (pinned in `.python-version`), managed with uv
- Frontend: MapLibre GL JS, plain JS ES modules, no build step. Keyless
  basemap (OpenFreeMap or Protomaps). May move to TypeScript + Vite later
  (triggers in `docs/web-plan.md`)
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
- OSM: pyosmium (`osmium`, added; reads `.osm.pbf` and `.osm` XML). It
  pulls in `requests`/`urllib3` (unused by us)
- Geometry: shapely + pyproj (added for tier B, `match/skipped.py`;
  project to EPSG:2272, US survey feet). Tier A's geometry stays
  hand-written (`match/crossings.py`, equirectangular metres).
- Graphs: networkx (added for tier C, `match/walk.py`): one street's
  ways per leg, shortest paths along it.

## Commands

- Run tests: `uv run pytest`; JS (pure modules only, no npm):
  `node --test web/test/`
- Lint/format: `uv run ruff check . && uv run ruff format .`
- Run everything from the repo root (default paths are relative to it).
  The map pipeline: `ingest` -> `match` -> `export site` -> serve.
- Fetch an alerts snapshot (from the repo root):
  `uv run python -m septa_detours.ingest` ->
  `data/raw/alerts/<UTC stamp>.json`. A `septa-detours fetch` CLI is
  planned but not built
- Fetch OSM extracts (occasionally, ~540 MB):
  `uv run python -m septa_detours.ingest osm` ->
  `data/raw/osm/{pennsylvania,new-jersey,delaware}-<YYMMDD>.osm.pbf`
- Build the street cache after fetching extracts (~30 s, ~1.2 GB RAM):
  `uv run python -m septa_detours.streets` ->
  `data/processed/streets.parquet`
- Parse + match a snapshot (~2 s; needs the bus GTFS and the street cache):
  `uv run python -m septa_detours.match [snapshot]` (default: newest in
  `data/raw/alerts/`) -> `data/processed/detours-<stamp>.json`; prints
  `(N detours: M matched to a route, K placed)`
- Export the data contract (~9 s, ~350 MB RAM; needs both GTFS feeds):
  `uv run python -m septa_detours.export site [detours.json]` (default:
  newest `detours-<stamp>.json`) -> `web/data/{status,routes}.json`,
  `{network,starts,skipped,paths}.geojson`, `routes/<feed>-<route_id>.json` (one per
  route, 181); overwrites in place, deletes route files of routes gone
  from GTFS. Types: `export/contract.py`
- Export one route's shapes (debugging tool, not used by the page):
  `uv run python -m septa_detours.export route bus 21` ->
  `web/data/bus-21.geojson`
- Serve the map: `python -m http.server -d web`, then open
  http://localhost:8000 (it reads the files `export site` writes)

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
- OSM names are spelled out with Philly's direction prefixes: alerts say
  `17th & Washington`, OSM has `South 17th Street` / `Washington Avenue`;
  `JFK Blvd` is `John F. Kennedy Boulevard`. The same name repeats across
  towns (`North Broad Street` exists in NJ/DE too), so a name pair alone
  isn't a location: check it against the route. OSM's `tiger:name_base`
  tag (bare name, e.g. `Broad`) isn't read and isn't needed:
  `osm_street_keys` drops the prefix itself.

## Conventions

- Type hints on all public functions.
- Small, pure functions where possible, especially in `parse/` and `match/`,
  so they're easy to test against fixtures.
- Prefer clear names over comments; use docstrings for intent and edge cases.
- Commit small and often. I review diffs, so keep changes focused.

## Current state

Tooling set up: dev deps (pytest, ruff), strict ruff config, lint passing,
pytest `testpaths = ["tests"]`. No CLI entry point yet; add
`[project.scripts]` back when building `fetch`.

Reached (history in `docs/notes/`, plans in `docs/`):

- **The pipeline**: `ingest` -> `match` (parse + match: route, shapes,
  start point, rejoin, skipped stretch, the detour's own path walked
  along OSM streets, daily hours) -> `export site` (the data contract,
  `export/contract.py`, **schema 9**) -> `web/`.
- **The page** (web plan W1-W6): sidebar / bottom sheet with search,
  mode chips, route list and a route panel of detour cards; focus via
  URL hash; keyboard and screen-reader pass.
- **Geography** (geography plan tiers A-C): start points, rejoins,
  skipped stretches (cut from the drawn line), detour paths with turn
  checks. Real `121123Z`: 63 paths of 97 candidates, 75 stretches.
- **UI/UX pass** (`docs/ui-plan.md`, U1-U8 + U5b, 2026-11-26): only
  detours in effect, by the page's clock and their daily hours; grey
  routes and magenta detours; route-number markers below zoom 13;
  focusing frames the detours; direction arrows on the focused route
  and on detour paths; a legend of what's drawn; cards with turns,
  hours and "Back on route ..."; each route-direction drawn once.
- Tests: ~1660 Python, ~156 JS. The map can be rendered headless
  (Brave + CDP, see `docs/notes/export-and-web.md`), not just by eye.

## Next

Agreed order (2026-11-26): a render sweep of everything built (by
Claude, headless), then the **color pass** (`docs/ui-plan.md`), then
the remaining follow-ups: script caching (web plan, hosting), the
off-route start lead-in and the two unchecked turns
(`docs/geography-plan.md`, tier C follow-ups), two-street detours,
`source_key` twins and message-vs-API questions (`docs/backlog.md`),
snapshot collection. Stop closures on the map (tier A step 4) may not
be needed: closures are well signed in person; detours aren't.

## Testing habits (cross-cutting)

Details and their origins are in `docs/notes/`; the short version:

- Mutation-check every increment: break the code, see a test fail. The
  runner is a scratch script (not committed): copy the target, apply
  `[(old, new), ...]` pairs that must each match exactly once, run pytest
  with `PYTHONDONTWRITEBYTECODE=1` and a fresh `PYTHONPYCACHEPREFIX`
  temp dir per mutant (a stale `.pyc` silently tests the
  wrong code), restore in `finally`. Before calling a survivor
  "equivalent", check it (e.g. `strict=False` is *not* equivalent for
  `read_detours`).
- Compare whole outputs; use realistic Philly coordinates (lon ~ -75, lat
  ~ 40) so lat/lon swaps show; make counts unequal so swaps show; a "tie"
  in float tests must be binary-exact.
- Pins break on purpose: adding a fixture breaks parse's `NOT_COMPLETE`,
  match's `FIXTURE_EXPECTED`, `NO_SHAPES`, `PLACED`, `NOT_NEAR_ROUTE`,
  `START_OUTCOMES` and the sweep counts. Review the new items, then
  update the pins.
- Ruff gotchas: SIM300 wants a module constant on the *right* of `==`;
  RUF001 flags literal en dashes / NBSPs (write `"\u2013"`, `"\u00a0"`;
  Claude has typed literal NBSPs before: `sed -i
  's/\xc2\xa0/\\u00a0/g' <file>`).
- ty: 47 pre-existing diagnostics (45, plus one per new `DetourNotice`
  field from `test_model.py`'s untyped `make_notice` helper) (mostly `**dict` test helpers and
  `dict` invariance vs `Properties`); don't add more.
- JS: `node --test web/test/` for pure modules (no DOM, no
  `maplibregl`). Tests set `process.env.TZ = "Asia/Tokyo"`: this machine
  is on New York time, so a missing `timeZone` would otherwise pass. The
  drawn map can't be checked headless; check it by eye.

## Detailed notes

`docs/notes/README.md` indexes one file per area (gtfs, ingest, streets,
model, fixtures, parse, match, export and web): what was built, why
(mostly my decisions), real-data numbers and test findings. Read the one
for the area you're about to touch before changing it, and add to it
(not to this file) when an increment lands. Keep this file short:
working rules, architecture, commands, data notes, current state.
