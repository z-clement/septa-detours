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
- Type checking: pyright, basic mode (optional, add later)
- Candidate libraries (ask before adding each): httpx (ingest),
  polars or pandas (GTFS), shapely + pyproj (match; project to EPSG:2272
  before measuring distances)

## Commands

- Run tests: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format .`
- Fetch data: `uv run septa-detours fetch` (planned, not built yet)
- Serve the map: `python -m http.server -d web` (planned; export writes
  GeoJSON to `web/data/`)

## Data notes

- Static GTFS joins: `routes` -> `trips` -> `shapes` (via `shape_id`) and
  `stop_times` -> `stops`. Remind me of this if I get tangled.
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
Stack chosen; project created with `uv init --package` (Python 3.13, `src/`
layout). Next steps: review `pyproject.toml`, load GTFS and plot one route,
then collect raw alerts into `data/raw/`. Defining the `Detour` model in
`model.py` is deferred until later.
