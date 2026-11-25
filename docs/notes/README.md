# Notes index

Detailed records of what was built, the decisions behind it (mostly the
user's), real-data numbers, and test/mutation findings. One file per area;
read the one for the area you're about to touch.

| File | Covers |
|---|---|
| `gtfs.md` | `gtfs/`: loaders, shapes, a route's shapes, directions |
| `ingest.md` | `io.py`, alerts ingest, the alerts API's shape and quirks |
| `streets.md` | OSM extracts (`ingest osm`) and the street cache (`streets/`) |
| `model.md` | `model.py` (shared types) |
| `fixtures.md` | alert fixtures, real snapshots, what the data looks like |
| `parse.md` | `parse/`: text, times, directions, notices, locations |
| `match.md` | `match/`: routes, directions, street names, crossings, tier A |
| `export-and-web.md` | `export/`, the match command, `web/` |

Plans live one level up: `../web-plan.md` (current), `../geography-plan.md`,
`../backlog.md`.

## Progress before "detours on the map"

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Before that: **tier A is wired in**: `match_notice` fills
`RouteMatch.start_point` (an OSM node near the route where the detour
starts) or adds a `"start: ..."` issue. Chain: notice `start_place` -> OSM
ways per name (`match/streets.py`) -> shared nodes grouped into crossings
-> the one crossing within 500 m of the route (`match/crossings.py`),
run by `match/place.py`. On real snapshots it places 110 of 140 and 134
of 166 notices, with **no ambiguous ones**. Before that: alert street
names normalize to OSM's,
and notices carry their
locations split into street names (`DetourNotice.start_place`/
`end_place`, from `parse/location.py`). Before that: **OSM street
data**: Geofabrik extracts
fetched by `ingest osm`, read and clipped by `streets/`, cached in
`data/processed/streets.parquet` (146,871 named road ways). Before that:
`match/` routes + directions (parsed notices -> `list[Detour]` via
`match_notices(notices, routes, trips, directions)`, with the GTFS route
and every shape in the notice's direction), `parse/` (snapshot bytes ->
`list[DetourNotice]` via `parse_snapshot`), and one route plotted with
MapLibre. No geometry for the detour itself yet (only its start point).
See `streets.md`, `../geography-plan.md` and `../web-plan.md`.
