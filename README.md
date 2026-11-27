# SEPTA Detours

[![test](https://github.com/z-clement/septa-detours/actions/workflows/test.yml/badge.svg)](https://github.com/z-clement/septa-detours/actions/workflows/test.yml)

A live map of the detours on SEPTA's buses, trolleys and trains, updated
every 15 minutes: **https://z-clement.github.io/septa-detours/**

SEPTA posts detours as short text notices, like route 2's "SB via 17th,
Left on Washington, Right on Broad, Right on Passyunk, Left on 17th, Reg
Rt". This project reads those notices,
works out where each detour leaves its route, which streets it takes and
where it rejoins, and draws that on a map alongside the stretch of route
it skips.

Unofficial: not affiliated with or endorsed by SEPTA. Check SEPTA's own
service alerts before you travel.

![Route 28 focused: a detour around a fallen tree, drawn as a dashed
path along Cresco Avenue, Welsh Road and Winchester Avenue, with the
turn-by-turn steps in the sidebar](docs/screenshot.png)

<sub>Basemap: [OpenFreeMap](https://openfreemap.org/) ©
[OpenMapTiles](https://www.openmaptiles.org/), data ©
[OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.</sub>

## How it works

A GitHub Actions job runs the pipeline every 15 minutes and publishes the
result to GitHub Pages:

1. **Ingest**: fetch SEPTA's alerts API (and, when a new one is out,
   SEPTA's GTFS schedule data), saving the raw responses untouched.
2. **Parse + match**: turn each notice's text into structured fields
   (direction, times, daily hours, the turn-by-turn steps), then tie it
   to the GTFS route and its shapes. Street names are matched to
   OpenStreetMap to place the start and rejoin points, and the detour's
   path is walked street by street.
3. **Export**: write the JSON and GeoJSON files the page reads (the
   "data contract", `src/septa_detours/export/contract.py`).

The page is plain JavaScript with [MapLibre GL JS](https://maplibre.org/)
and no build step. It shows only the detours in effect at the moment you
look, by their dates and daily hours.

**A wrong map is worse than an incomplete one.** A notice that can't be
read without guessing (an unclear location, streets that don't meet, a
step that doesn't parse) is still listed, but isn't drawn. About two
thirds of detours get a place on the map, and about a third a full path.
Detours on routes H, L, R and XH aren't matched to a route yet: SEPTA's
alerts still use the routes' old names, and the schedule data doesn't
say which old name became which new one.

## Running it locally

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.13) and,
for the JavaScript tests, Node 20 or newer. Run everything from the repo
root:

```sh
uv sync

# Reference data (occasionally)
uv run python -m septa_detours.ingest gtfs     # SEPTA's GTFS release in effect
uv run python -m septa_detours.gtfs unpack     # -> data/gtfs/
mkdir -p data/processed && curl -fL -o data/processed/streets.parquet \
  https://github.com/z-clement/septa-detours/releases/download/reference/streets.parquet
# ...or build the street cache from OpenStreetMap (~540 MB download, ~1.2 GB RAM):
#   uv run python -m septa_detours.ingest osm && uv run python -m septa_detours.streets

# The pipeline (each run takes seconds)
uv run python -m septa_detours.ingest          # an alerts snapshot
uv run python -m septa_detours.match           # parse + match it
uv run python -m septa_detours.export site     # -> web/data/

python -m http.server -d web                   # open http://localhost:8000
```

Tests and lint:

```sh
uv run pytest
node --test web/test/
uv run ruff check . && uv run ruff format --check .
```

The tests use saved real alerts (`tests/fixtures/`) and never touch the
network. Every command, with what it reads and writes, is listed in
[`CLAUDE.md`](CLAUDE.md) under "Commands".

## Layout

```
src/septa_detours/   the pipeline: ingest/, parse/, match/, export/,
                     plus shared GTFS and OpenStreetMap readers (gtfs/,
                     streets/) and the shared types (model.py)
web/                 the map page (index.html, js/, css/) and its tests
tests/               pytest, with real alerts in tests/fixtures/
docs/                operating.md (running the hosted site), the plans,
                     and notes/ (what was built and why, area by area)
.github/workflows/   publish.yml (the 15-minute job), test.yml (CI)
```

## How it was built

This is a learning project, written step by step with Claude (Anthropic's
AI assistant) under review: small increments, tests from real data, and
mutation checks. [`CLAUDE.md`](CLAUDE.md) holds the working rules, and
`docs/` holds the plans and notes from the process, written from the
author's point of view.

## Data and credits

- **SEPTA**: detour notices from SEPTA's alerts API; routes and shapes
  from SEPTA's [GTFS data](https://www3.septa.org/developer/), used
  under its license. `tests/fixtures/alerts/` holds saved API
  responses.
- **OpenStreetMap**: street data © OpenStreetMap contributors, under the
  [Open Database License](https://www.openstreetmap.org/copyright). The
  detour paths the site publishes (`data/paths.geojson`), the street
  cache (the `reference` release) and `tests/fixtures/osm/` are derived
  from it, and are available under the ODbL too.
- **Basemap**: [OpenFreeMap](https://openfreemap.org/) and
  [OpenMapTiles](https://www.openmaptiles.org/).
- **[MapLibre GL JS](https://maplibre.org/)** (BSD-3-Clause), loaded
  from unpkg.

## License

The code is under the [MIT License](LICENSE). The data above keeps its
own terms.
