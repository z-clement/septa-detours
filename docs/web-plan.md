# Web plan: data contract and map app

Status: **P1-P5 done** (`export/simplify.py`, `contract.py`, `site.py`); P6 next. Written
2026-11-25 for a future session to pick up. Work through it with the usual rules in `CLAUDE.md` (small
increments, tests from real data, mutation checks, stop for review after
each). Items marked **Confirm** are proposals the user hasn't approved
yet: ask before building them.

## Goal

Turn the detours map into a usable **one-stop shop for the current state
of SEPTA**: the whole network on one map, every route findable, any route
focusable to see its detours. No trip routing. Later (make room, don't
build): live vehicles, stops + closures, rail status (the user's picks;
not the API's text advisories, for now). Possibly hosted
with live fetching, maybe as a spin-off project.

Decided by the user:
- **Layout: map + route sidebar.** Search + route list grouped by mode,
  a detour badge per route, detoured routes first. The map shows the whole
  network faintly and detoured routes in color. Clicking a route (in the
  list or on the map) focuses it: zoom to it, dim the rest, list its
  detours in the panel.
- **Data: overview + detail on focus.** A small whole-network file loaded
  once; a per-route detail file fetched when a route is focused.
- **Frontend: plain JS ES modules, no build step**, for now. We may switch
  to TypeScript + Vite later (see "Later: TypeScript + Vite").
- **The data contract comes first** (Python export), then the web work.

## Facts this plan rests on

Measured 2026-11-25 on the current GTFS (both feeds) and snapshot
`2026-11-25T121123Z` (scratch scripts, not committed):

- 181 routes: bus feed 152 bus (type 3), 8 trolley (0), 5 metro (1),
  3 trackless (11); rail feed 13 regional rail (2). No route lacks a
  color. 6 bus routes have **no trips/shapes** (`MANN`, `T_BUS`, `D1_BUS`,
  `D2_BUS`, `NOR_BUS`, `WTR_BUS`: substitution shuttles).
- `route_short_name` differs from `route_id` for 9 routes (`L1_OWL` ->
  `L1 OWL`, `T_BUS` -> `T Bus`, ...). Non-numeric bus names: `B1 OWL`,
  `BLVDDIR`, `D1 Bus`, `D2 Bus`, `FOX Bus`, `K`, `L1 OWL`, `LUCYGO`,
  `LUCYGR`, `M1 Bus`, `MANN`, `NOR Bus`, `T Bus`, `WTR Bus`.
- 341 route-directions, 1,006 shapes in use, 531k shape points. All shapes
  drawn raw: ~12 MB of GeoJSON.
- Every route-direction has a `directions.txt` row. Names: Northbound 80,
  Southbound 79, Eastbound 79, Westbound 78, Inbound 17, Outbound 17,
  Loop 3.
- **"The shape most trips use" is a bad representative**: it differs
  from the longest shape in 116 of 341 route-directions, and is often a
  short-turn (route 55: 36% of the longest; 24, 26, 115 similar).
- **Covering set**, as decided (longest first, drop a shape when every
  point lies within 20 m of *some* already-kept shape of the same
  route-direction; compared on 2 m-simplified lines): **593** of 1,006
  shapes kept; 200 route-directions need 1, 141 need 2+, max 8. Route 24:
  4 -> 1; route 55: 6 -> 4/5 (real branches); route 14 dir 0: 20 -> 6.
  The rejected rule (one kept shape must cover every point) kept 620
  (622 on another run, 629 on raw shapes; max 9, route 14 dir 0).
  ~4.4 s for all shapes, plus ~2.4 s to simplify them at 2 m.
- Douglas-Peucker simplification (equirectangular metres) + coordinates
  rounded to 5 decimals (~1 m):
  - overview from the covering set at 5 m tolerance: **~1.0 MB**, 44k points
    (measured with the 622-shape rule; the 593 kept now should be a bit less);
  - most-trips shapes only: 4.8 MB raw -> 0.53 MB at 5 m, 0.40 MB at 10 m;
  - per-route detail, all shapes raw: median 38 KB, max 460 KB (route
    14, 38 shapes); at 2 m: max ~107 KB.
- Detours (`121123Z`): 166 total, 161 matched to a route, 134 placed;
  5 not matched, all old Bus Revolution names (API routes H x2, L x2,
  R). 14 matched detours have no shapes (e.g. route 68's two "EB" items:
  the route has no EB direction), so `direction_id` is null for them.
- `stop_times.txt`: bus 133 MB, rail 1.6 MB (matters for stops later:
  use lazy `scan_csv`).

## Part 1: the data contract

Everything the page reads, produced by one export command from a detours
file + GTFS. The page never reads anything else. Hosting, cron jobs or a
server can replace how the files are produced without touching the
page.

### Files

All under `web/data/` (gitignored):

```
web/data/
  current.json                  pointer to the newest build (written last)
  builds/<build id>/
    status.json                 provenance + totals + unmatched detours
    routes.json                 the route catalog (sidebar), display order
    network.geojson             overview lines, all routes, simplified
    starts.geojson              start points of all placed detours
    routes/<feed>-<route_id>.json   detail for one route (on focus)
```

**Decided** (D3, the user's): **plain overwrite** of the files in
`web/data/` (no history needed); the build directories and
`current.json` below are dropped in P6. The rejected option: builds in
their own directory + a pointer file. Each
file is written atomically already (`write_bytes_atomic`), but a *set* of
files isn't: a page loading mid-export could mix old `routes.json` with
new `network.geojson`. Writing a whole build to `builds/<id>/` and then
replacing `current.json` (atomically, last) makes a build appear all at
once. It also suits static hosting later (build files never change, so
they cache forever; only `current.json` must not be cached). Keep the
newest 3 builds, delete older ones after the pointer moves. The simpler
alternative is plain overwrite of `web/data/*.json` (accepting a rare
mixed read).

`<build id>` = the snapshot stamp plus a short content hash, e.g.
`2026-11-25T121123Z-3f9a1c2e`, so re-exporting the same snapshot with new
GTFS or code gives a new directory.

### `current.json`

```json
{"schema_version": 1, "build": "builds/2026-11-25T121123Z-3f9a1c2e/"}
```

- `schema_version`: an integer, bumped on any breaking change to any
  file. The page refuses a version it doesn't know, with an error naming
  the export command (a stale page or stale data, not a silent half-map).
- `build`: path relative to `web/data/`, ends with `/`.

### `status.json`

```json
{
  "schema_version": 1,
  "generated_at": "2026-11-25T17:02:11Z",
  "snapshot": "2026-11-25T121123Z.json",
  "snapshot_fetched_at": "2026-11-25T12:11:23Z",
  "gtfs": {"bus": "...", "rail": "..."},
  "detours": {"total": 166, "matched": 161, "placed": 134},
  "unmatched": [ <detour object>, ... ]
}
```

- `snapshot_fetched_at` comes from the snapshot's stamp name (UTC). A
  hand-named snapshot gives `null`.
- `gtfs`: a provenance string per feed (e.g. `feed_info.txt` version, or
  the newest file mtime). **Confirm** which; GTFS provenance isn't
  recorded anywhere yet.
- `unmatched`: detours whose route isn't in GTFS (the API's H, L, R).
  Matched detours with no shapes (route 68's "EB" items) aren't here:
  they're in their route's detail. The page lists these in a "Not on the map" section
  so nothing silently disappears. Same detour object as in route detail
  (below), with `route` = the API route name instead of a GTFS key.

### `routes.json`

A JSON list in **display order**. Python decides the order; the page
keeps it.

```json
[
  {
    "key": "bus-21",
    "feed": "bus",
    "route_id": "21",
    "short_name": "21",
    "long_name": "Chestnut-Walnut",
    "mode": "bus",
    "color": "#EF3340",
    "text_color": "#FFFFFF",
    "has_shapes": true,
    "bounds": [[-75.26, 39.94], [-75.14, 39.97]],
    "detours": {"total": 2, "placed": 1}
  }
]
```

- `key` = `<feed>-<route_id>`, the same rule (and `_SAFE_ROUTE_ID` check)
  as `route_geojson_path`. It's the only route ID the page uses (file
  name, URL hash, map filters). `route_id` alone isn't unique across
  feeds.
- `mode` from `route_type`: 0 `trolley`, 1 `metro`, 2 `rail`, 3 `bus`,
  11 `trackless`. An unknown type raises in export (GTFS changed: look).
- Order: modes metro, trolley, trackless, bus, rail (**Confirm**); within
  a mode a natural sort on `short_name` (numbers by value first, then the
  rest alphabetically, case-insensitive): `1, 2, ..., 124, BLVDDIR, K,
  ...`. "Detoured first" is a page-side grouping (it changes with every
  snapshot); the base order stays stable.
- `has_shapes: false` for the 6 shapeless routes, with `bounds: null`.
  **Confirm** (D4): list them greyed ("no scheduled service in this
  GTFS"), since substitution shuttles matter exactly when they run.
- `detours.total` counts matched detours (placed or not); `placed` counts
  those with a start point.

### `network.geojson`

A FeatureCollection of LineStrings: the **covering set** of each
route-direction (D1 decided, see Facts), simplified at **5 m**
(D2 decided), coordinates rounded to 5 decimals.

Properties, kept minimal (this file is loaded once, up front):
`key`, `direction_id`, `mode`, `color`. Everything else comes from
`routes.json` by `key`. Order: `routes.json` order, then `direction_id`,
then most trips first (`route_shapes` order). Real: 593 lines, 42k
points, 0.97 MB, simplified from the raw shapes (not the 2 m lines).

### `starts.geojson`

A FeatureCollection of Points, one per placed detour (all routes), for
the overview dots. Properties: `key` (route), `source_key`, `color`,
`timing` (see "Detour timing"). Clicking a dot focuses its route and
selects that detour; the details come from the route's detail file.

### `routes/<key>.json`

Fetched when a route is focused. Every route with shapes or detours gets
one.

```json
{
  "schema_version": 1,
  "key": "bus-21",
  "directions": [
    {"direction_id": 0, "name": "Eastbound", "destination": "Penn's Landing"},
    {"direction_id": 1, "name": "Westbound", "destination": "69th St TC"}
  ],
  "shapes": { "type": "FeatureCollection", "features": [ ... ] },
  "detours": [ <detour object>, ... ]
}
```

- `shapes`: **every** shape of the route (not the covering set): branches
  and short-turns matter when focused. Simplified at **2 m**, 5
  decimals. Properties: `shape_id`, `direction_id`, `trip_count` (trips
  using it), `covering` (bool: in the overview's covering set), `color`.
- `detours`: every matched detour on this route, placed or not, in
  snapshot order.

### The detour object (route detail and `status.unmatched`)

```json
{
  "source_key": "5d0d22dfe7d86935",
  "route": "bus-2",
  "status": "complete",
  "direction": "SB",
  "direction_id": 0,
  "location_start": "17th & Washington",
  "location_end": "17th & Mifflin",
  "start": "2026-11-11T06:30:00-05:00",
  "end": "2026-11-27T16:00:00-05:00",
  "reason": "Contractor",
  "message": "7am - 4pm Mon thru Fri, ...",
  "issues": ["start: ..."],
  "start_point": {"lon": -75.1716, "lat": 39.9385, "node_id": 110024066},
  "shape_ids": ["317310"]
}
```

- Plain JSON, not GeoJSON properties, so `issues` stays a **list** and
  `start_point`/missing values are explicit `null` (MapLibre's
  null-dropping only affects feature properties).
- `direction_id`: from `RouteMatch.shapes` when they all agree, else
  `null`. `shape_ids`: `RouteMatch.shapes`, in order.
- `route`: a route `key` for matched detours. For `status.unmatched` it's
  the API `route_id` (`bus_route_H`) and `shape_ids` is `[]`. Built by
  `detour_object(detour)` (no `key` argument: it derives `route` itself).
- `message` is the raw API text. Times are ISO 8601 with the parsed
  offset (as `detour_properties` does today).

### Detour timing

Whether a detour is in effect depends on *when you look*, so the page
computes it, not export: `active` (start <= now <= end), `upcoming`
(start > now), `ended` (end < now), `unknown` (a time missing). The one
exception is `starts.geojson`'s `timing`, computed at export time **only
as a default** for styling before the page recomputes it. Keep the rule
in one pure JS function with tests. Known limit: recurring windows ("7am
- 4pm Mon thru Fri") aren't parsed, so "active" means "inside the overall
start/end", not "running right now".

### Python: where it lives

Export stays the only stage involved (it reads `Detour` JSON + GTFS;
nothing reaches into parse/match).

- `export/simplify.py` (pure): `simplify_line(line, tolerance_m)`
  (Douglas-Peucker in local equirectangular metres; endpoints always
  kept; never fewer than 2 points); `round_line(line, decimals)` (decided:
  drops consecutive duplicates that rounding creates, but always keeps at
  least 2 points); `covering_shapes(lines: Mapping[shape_id, line],
  tolerance_m=20) -> list[shape_id]` (decided: longest first in metres;
  keep unless every point is within `tolerance_m` of *any* already-kept
  line; pass 2 m-simplified lines, since only points are checked). Geometry comes
  from the shared `septa_detours/geo.py` (decided: `distance_to_line_m`
  moved there from `match/crossings.py`), never from `match/`.
- `export/contract.py` (pure): TypedDicts for every file above (the
  contract's Python source of truth, like `geojson.py`'s types) and
  `SCHEMA_VERSION = 1`.
- `export/site.py` (pure builders): `route_mode`, `route_sort_key`,
  `route_catalog(...)`, `network_collection(...)`, `starts_collection(...)`,
  `route_detail(...)`, `detour_object(detour, key)`, `status(...)`.
  Reuse `route_properties`/`_css_color` logic where it fits.
- `export/write.py` (I/O): `write_build(files: dict[relative path,
  bytes], root=web/data) -> build dir` (writes the directory, then
  `current.json`, then prunes old builds), JSON encoding as
  `write_geojson` does (`allow_nan=False`, UTF-8, compact).
- `export/__main__.py`: a new subcommand `export site [detours.json]`
  (newest by default, like `export detours`). Needs `load_directions` and
  both feeds' routes (rail routes appear in the catalog even without
  detours). **Confirm** (D7): `export detours` stays until the web part
  stops reading `detours.geojson` (step W2), then is removed.
  `export route` stays as a debugging tool (decided).

## Part 2: the web app (plain JS)

### Module layout

```
web/
  index.html          layout only: #sidebar, #map, #status, #error
  css/app.css         styles moved out of index.html
  js/main.js          bootstrap: load data, build map + sidebar, wire state
  js/data.js          fetch current.json -> build files; schema check;
                      route detail cache (Map key -> Promise)
  js/state.js         one state object + subscribe(); URL hash sync
  js/mapview.js       MapLibre sources/layers/events (the only module
                      that touches maplibregl)
  js/sidebar.js       renders the route list and the route panel (DOM)
  js/routes.js        PURE: group by mode, detoured-first, search filter
  js/detours.js       PURE: timing(detour, now), sort, summaries
  js/format.js        PURE: times (America/New_York), labels, plurals
  test/*.test.js      node --test for the PURE modules
```

- **Pure modules** import nothing from the DOM or `maplibregl`, so
  `node --test web/test/` can run them (Node 20 is installed; no npm,
  no dependencies). This replaces the scratch Node checks used so far.
- Optional, later: JSDoc types + a `jsconfig.json` with `checkJs`, run
  occasionally with `npx tsc --noEmit` (the JS counterpart of ty). Needs
  npm/npx at check time only; **ask** before adding.
- MapLibre stays 5.24.0 UMD from unpkg (global `maplibregl`); see
  CLAUDE.md for why not v6 without a build.

### State

One plain object, changed only through small functions in `state.js`
that then notify subscribers (sidebar and map re-render from state):

- `focus`: route key or `null` (overview).
- `selectedDetour`: `source_key` or `null`.
- `search`: string. `modes`: set of visible modes (default: all).
- `now`: a `Date`, refreshed every minute (timing changes over time).
- URL hash mirrors `focus`/`selectedDetour` (`#route=bus-21&detour=5d0d...`),
  so links are shareable and the browser Back button leaves a route.

### Overview (no route focused)

- Status line: "Detours as of Nov 25, 7:11 AM: 166 total, 134 on the
  map, 27 without a location, 5 not matched to a route" (from
  `status.json`; times in America/New_York).
- Map: `network.geojson` faint (low opacity, thin, mode color or route
  color: **Confirm**), detoured routes (by `routes.json` counts) drawn in
  full route color and thicker, `starts.geojson` dots on top, styled by
  `timing` (active solid, upcoming hollow, ended grey).
- Sidebar: search box, mode filter chips, then "Detoured now" (routes
  with active detours, by count), then every route grouped by mode in
  `routes.json` order, each row: colored badge with `short_name`,
  `long_name`, detour count. Shapeless routes greyed. A "Not on the map"
  section lists `status.unmatched`.
- Click a line or dot on the map, or a sidebar row -> focus that route
  (a dot also selects its detour). If several routes' lines are under the
  click, show a small chooser popup instead of guessing.

### Route focused

- Fetch `routes/<key>.json` (cached). Map: fit `bounds`; network dimmed
  further; the route's own shapes in full color, offset by direction (as
  today), covering shapes thicker than short-turns; its detours' dots.
- Panel: route header (badge, names, back button), direction names,
  detours grouped by timing (active, upcoming, ended, unknown). Each card:
  times, from -> to, direction, reason, message, issues; "location not
  found" when `start_point` is null (still listed: unplaced detours are
  the 32 the map can't show).
- Hover a card -> highlight its dot; click a dot -> select and scroll to
  its card; Escape or Back -> overview.

### Later in the web part

- Mobile (< ~700 px): the sidebar becomes a bottom sheet.
- Keyboard and screen readers: rows and cards are real `<button>`s,
  visible focus, `aria-live` status.
- Stops + closures, live vehicles, rail status: new layers and panel
  sections fed by new contract files (bump `schema_version` or add
  optional files). Live vehicles need data refreshed every ~15-30 s,
  which static builds can't do: a live endpoint (or a proxy, if SEPTA's
  API lacks CORS headers: **check** before planning it) outside the
  build directory.

## Order of work

Each step: tests, lint, ty, mutation check, stop for review. Python
first, so the web steps have real files to read.

Python (the contract):
1. **P1** (done) `export/simplify.py`: `simplify_line` + `round_line`.
   Hand-built lines (a straight line collapses to its endpoints; a corner
   survives above tolerance and goes below it; 2-point lines unchanged).
2. **P2** (done) `covering_shapes`. Hand-built short-turn, branch,
   stitched and reversed cases; real data: 593 of 1,006 at 20 m.
3. **P3** `export/contract.py` types + `route_mode`, `route_sort_key`,
   `route_catalog`. Real names from the Facts list for the sort.
4. **P4** `detour_object` + `route_detail` (directions, all shapes at
   2 m, detours).
5. **P5** `network_collection`, `starts_collection`, `status`.
6. **P6** `write_build` (directory, pointer, pruning; atomic pointer
   last) + the `export site` subcommand. Real run: report file sizes.

Web (plain JS):
7. **W1** Split `map.js` into the modules above with **no visible
   change** (still reads `detours.geojson`); `node --test` for
   `format.js`. Fix the "1 lines" plural while here.
8. **W2** `data.js` reads `current.json` -> `status`, `routes`,
   `network`, `starts`; overview map + status line. Then remove `export
   detours` (if D7 confirmed).
9. **W3** Sidebar: grouped list, search, mode chips, "Detoured now",
   "Not on the map". `routes.js` + `detours.js` with tests.
10. **W4** Focus: detail fetch + cache, map focus, panel with detour
    cards, URL hash, Back/Escape.
11. **W5** Card <-> dot linking, the multi-route click chooser.
12. **W6** Mobile bottom sheet, keyboard/a11y pass.

## Decisions to confirm (with recommendations)

- **D1** (decided) Overview shapes: covering set at 20 m, where a shape
  is covered if every point is near *any* kept shape (so shapes stitched
  from kept branches are dropped too). Rejected: one kept shape must
  cover it all; the longest shape per route-direction (loses real
  branches, e.g. route 55).
- **D2** (decided, for now) Simplification: overview 5 m, detail 2 m, 5 decimals
  (recommended). 10 m overview saves little more (0.40 vs 0.53 MB on
  single shapes).
- **D3** (decided) Plain overwrite of `web/data/` (accepting a rare mixed
  read mid-export). Rejected: build directory + `current.json` pointer.
- **D4** Shapeless routes listed greyed (recommended) vs. omitted.
- **D5** Unmatched detours in `status.json` + a "Not on the map" section
  (recommended).
- **D6** Ended detours shown in a collapsed "Ended" group (recommended)
  vs. hidden.
- **D7** `export site` replaces `export detours` once W2 lands
  (recommended).
- **D8** Mode order metro, trolley, trackless, bus, rail; faint network
  colored by route color vs. one neutral grey.
- GTFS provenance string in `status.json` (`feed_info.txt` vs. file
  mtimes).

## Later: TypeScript + Vite

Switch when the app outgrows plain modules. Likely triggers: live
vehicles (frequent re-renders), the hosted spin-off, or MapLibre v6
(ESM-only; needs bundling). The module layout above maps one-to-one onto
`.ts` files; JSDoc types become TS types; `node --test` tests move to
Vitest; MapLibre comes from npm. The data contract doesn't change, which
is the point of defining it first.

## Later: hosting with live fetching

Probably a spin-off that reuses this pipeline and contract. Cheapest
first: (1) static hosting + a scheduled job (every 5-10 min) running
`ingest -> match -> export site` and publishing `web/` (GTFS and the
24 MB street cache cached between runs, rebuilt rarely); (2) the same
plus a small proxy for live vehicles, if needed; (3) a real backend only
if those fall short. `current.json` must be served uncached; build
directories can be cached forever.
