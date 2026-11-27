# Web plan: data contract and map app

Status: **P1-P6, W1, W2, W3 done** (the page draws the data contract
and the route sidebar: grouped list, search, mode chips, "Detoured
now", "Not on the map"). **W4 (focus a route) next**: confirm its open
decisions first (see W4 in "Order of work"). Written
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
  status.json                   provenance + totals + unmatched detours
  routes.json                   the route catalog (sidebar), display order
  network.geojson               overview lines, all routes, simplified
  starts.geojson                start points of all placed detours
  routes/<feed>-<route_id>.json detail for one route (on focus)
```

**Decided** (D3, the user's): **plain overwrite** of these files on each
export (no history needed). Each file is replaced atomically
(`write_bytes_atomic`), but the set isn't: a page loading mid-export may
rarely mix old and new files (accepted). Route files for routes that no
longer exist are deleted after the new ones are written. The page reads
`status.json` first and refuses a `schema_version` it doesn't know, with
an error naming the export command. Versions: 1, the first contract; 2,
`routes.json` gains `detours.windows` (W3; the page needs it, so old
data is refused rather than read silently wrong) (a stale page or stale data, not a
silent half-map). Rejected: each export in its own `builds/<id>/`
directory plus a `current.json` pointer written last (all-at-once
builds, cache-friendly for hosting; revisit if mixed reads ever matter).

### `status.json`

```json
{
  "schema_version": 2,
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
    "detours": {
      "total": 2,
      "placed": 1,
      "windows": [["2026-11-11T06:30:00-05:00", "2026-11-27T16:00:00-05:00"],
                  ["2026-11-19T10:00:00-05:00", null]]
    }
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
  Decided (D4): listed greyed ("no scheduled service in this GTFS"),
  since substitution shuttles matter exactly when they run.
- `detours.total` counts matched detours (placed or not); `placed` counts
  those with a start point.
- `detours.windows` (added in W3, schema 2; decided): one `[start, end]`
  per matched detour, placed or not, snapshot order; ISO 8601 as in the
  detour object, `null` when unknown. The page computes each one's
  timing from it, so "Detoured now" needs no route files. Why: only
  `starts.geojson` had timing, and only for placed detours (27 matched
  detours on `121123Z` aren't placed). Real: 161 windows, `routes.json`
  ~60 KB.

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

Fetched when a route is focused. Every catalog route gets one (decided
in P6: even shapeless routes without detours, so the page never asks for
a missing file; the shuttles' files carry their directions).

```json
{
  "schema_version": 2,
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
  `SCHEMA_VERSION` (now 2; `web/js/data.js` has the same number).
- `export/site.py` (pure builders): `route_mode`, `route_sort_key`,
  `route_catalog(...)`, `network_collection(...)`, `starts_collection(...)`,
  `route_detail(...)`, `detour_object(detour, key)`, `status(...)`.
  Reuse `route_properties`/`_css_color` logic where it fits.
- `export/write.py` (I/O): `write_site(files: dict[relative path,
  JSON value], root=web/data)` (each file atomically, then deletes stale
  `routes/<key>.json`), JSON encoding as `write_geojson` does
  (`allow_nan=False`, UTF-8, compact).
- `export/__main__.py`: a new subcommand `export site [detours.json]`
  (newest by default). Needs `load_directions` and both feeds' routes
  (rail routes appear in the catalog even without detours). `export
  detours` was removed in W2 (D7, decided). `export route` stays as a
  debugging tool (decided).

## Part 2: the web app (plain JS)

### Module layout

```
web/
  index.html          layout only: #sidebar, #map, #status, #error
  css/app.css         styles moved out of index.html
  js/main.js          bootstrap: load data, build map + sidebar, wire state
  js/data.js          fetch status.json (schema check) + the others;
                      route detail cache (Map key -> Promise)
  js/state.js         one state object + subscribe(); URL hash sync
  js/mapview.js       MapLibre sources/layers/events (the only module
                      that touches maplibregl)
  js/sidebar.js       renders the route list and the route panel (DOM):
                      renderRouteList, createModeChips (W3)
  js/routes.js        PURE: timingCounts, detouredNow, groupByMode,
                      visibleRoutes,
                      searchRoutes (+ W2's detouredRoutes, routesBounds)
  js/detours.js       PURE: detourTiming(start, end, now); later sort,
                      summaries
  js/format.js        PURE: times (America/New_York), labels, plurals
  js/sheet.js         PURE (W6): the mobile sheet's heights
  js/dom.js           DOM helpers shared by sidebar and chooser (W5)
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
  with at least one active detour by `detours.windows`, most active
  first, ties in catalog order; routes with only upcoming/ended/unknown
  detours stay in their mode group), then every route grouped by mode in
  `routes.json` order (groups in the order Python wrote; headings from
  `modeLabel`: Metro, Trolleys, Trackless Trolleys, Buses, Regional
  Rail), each row: colored badge with `short_name`, `long_name`, detour
  count by timing ("3 now, 4 later"). Shapeless routes greyed. A "Not
  on the map" section lists `status.unmatched` (only in the unfiltered
  list: blank search, every chip on).
- Search (decided): case and surrounding spaces ignored, blank keeps
  all. A number (digits only) is a route number: it matches only at the
  start of `short_name` (`2` finds 2, 21, 204; not 12, and not route 5,
  whose long name is "2nd-Market to ..."). Anything else matches anywhere
  in `short_name` or `long_name` (`owl` finds both OWL buses). Ranking
  (decided 2026-11-25): a single letter was noisy (`k` matched 62
  routes via "Frankford"; route K was 58th), so text matches whose
  `short_name` starts with the query come first, then the rest, each in
  catalog order. Ranking reorders routes *within* a mode group only: the
  groups keep the catalog's mode order (`groupByMode(routes,
  modeOrder)`). Rejected: the best match's group moving to the top.
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

- **UI/UX pass: the map must be readable at a glance** (in progress:
  `docs/ui-plan.md`) (yours,
  2026-11-26, after tier C). Now that the map shows routes, detoured
  routes, faded skipped stretches, dashed detour paths and start dots
  (plus the network, focus dimming and direction offsets), it needs a
  dedicated design pass so someone glancing at it can tell what's
  detoured, where, and what to do. A big piece of work, not a tweak:
  plan it (questions, sketches, by-eye checks on real data) before
  building.
- ~~Detoured lines in a different line style~~ (done: tier B/C and the
  UI pass: faded stretches, dashed magenta paths).
- ~~Mobile (< ~700 px): the sidebar becomes a bottom sheet~~ (W6).
- ~~Keyboard and screen readers~~ (W6).
- Stops + closures, live vehicles, rail status: new layers and panel
  sections fed by new contract files (bump `schema_version` or add
  optional files). Live vehicles need data refreshed every ~15-30 s,
  which static builds can't do: a live endpoint (or a proxy, if SEPTA's
  API lacks CORS headers: **check** before planning it) outside
  `web/data/`'s static files.

## Order of work

Each step: tests, lint, ty, mutation check, stop for review. Python
first, so the web steps have real files to read.

Python (the contract):
1. **P1** (done) `export/simplify.py`: `simplify_line` + `round_line`.
   Hand-built lines (a straight line collapses to its endpoints; a corner
   survives above tolerance and goes below it; 2-point lines unchanged).
2. **P2** (done) `covering_shapes`. Hand-built short-turn, branch,
   stitched and reversed cases; real data: 593 of 1,006 at 20 m.
3. **P3** (done) `export/contract.py` types + `route_mode`, `route_sort_key`,
   `route_catalog`. Real names from the Facts list for the sort.
4. **P4** (done) `detour_object` + `route_detail` (directions, all shapes at
   2 m, detours).
5. **P5** (done) `network_collection`, `starts_collection`, `status`.
6. **P6** (done) `write_site` (overwrite, delete stale route files) +
   the `export site` subcommand. Real run: 185 files, 3.6 MB, ~9 s.

Web (plain JS):
7. **W1** (done) Split `map.js` into the modules above with **no visible
   change** (still reads `detours.geojson`); `node --test` for
   `format.js`. Fix the "1 lines" plural while here.
8. **W2** (done) `data.js` reads `status` (schema check), `routes`,
   `network`, `starts`; overview map + status line. Then remove `export
   detours` (D7: done).
9. **W3** (done) Sidebar: grouped list, search, mode chips, "Detoured now",
   "Not on the map". `routes.js` + `detours.js` with tests. Details:
   `notes/export-and-web.md`.
   - Step 1 (done): `routes.json` `detours.windows` + schema 2 (Python,
     `data.js`).
   - Step 2 (done): the pure logic: `detourTiming` (`detours.js`),
     `timingCounts`, `detouredNow`, `groupByMode`, `searchRoutes`
     (`routes.js`), `modeLabel` (`format.js`). 60 JS tests.
   - Step 3 (done): the sidebar DOM (`sidebar.js`, HTML, CSS). Decided
     2026-11-25: (a) layout: a fixed left panel ~320 px, map fills the
     rest, the status line moves to the top of the panel (rejected: a
     panel floating over the map); (b) mode chips toggle modes (all on
     by default) and combine with search (a route must pass both); a
     chip with no matching routes is greyed, not hidden; chips filter
     the sidebar only, not the map (for now); (c) state stays in
     `main.js` until `state.js` (W4); `now` refreshes every minute and
     re-renders the sidebar; (d) rows are `<button>`s but clicking does
     nothing yet (focus is W4). Also decided while building: row counts
     by timing ("3 now, 4 later", not a total); search ranking (see
     Overview); "Not on the map" only in the unfiltered list (blank
     search, every chip on; rejected: always shown, or searchable).
10. **W4** (done) Focus: detail fetch + cache, map focus, panel with detour
    cards, URL hash, Back/Escape. Move state into `state.js`. Decided
    2026-11-25: (a) D6: ended detours in a collapsed "Ended (n)" group
    at the bottom of the panel (groups: active, upcoming, unknown, then
    ended); (b) focused map: the network fainter still, other detoured
    routes lose their color and their dots are hidden, the focused
    route's shapes in color (covering thicker than short-turns) with its
    own dots, map fits the route; (c) the route panel replaces search,
    chips and list (status line stays); Back/Escape restores them as
    they were; (d) an unplaced detour's card stays in its timing group
    with a muted "Location not found on the map" line. Known gaps from
    W3 to fix with the state work: the per-minute rebuild closes opened
    "Not on the map" items and drops keyboard focus inside the list.
    - Step 1 (done): `state.js` (pure): the store (`subscribe`, setters) and
      the URL hash (`parseHash`, `formatHash`).
    - Step 2 (done): `groupByTiming` (`detours.js`) + card text (`format.js`).
    - Step 3 (done): the route panel DOM (`sidebar.js`, HTML, CSS).
    - Step 4 (done): the focused map (`mapview.js`).
    - Step 5 (done): wiring (`main.js`): row/line/dot clicks focus, hash,
      Back/Escape, the W3 gaps.
11. **W5** (done) Card <-> dot linking, the multi-route click chooser.
    Decided 2026-11-25: (a) hovering a card highlights its dot; clicking
    a card selects it (highlighted card, selected dot style, URL hash)
    and pans the map to its dot only if it's off screen, no zoom
    (unplaced cards are just selected); a dot click selects and scrolls
    its card into view; (b) the chooser, when a click hits several
    routes: dots under the click give one button per detour (route
    badge + headline, from the route files); only lines give one button
    per route (badge + name); a button focuses that route (and selects
    that detour). Every hit on one route focuses it directly (as W4).
    - Step 1 (done): `clickChoices` (pure, `routes.js`).
    - Step 2 (done): the chooser popup (DOM), replacing the text popups.
    - Step 3 (done): dot states (hover, selected) on the map.
    - Step 4 (done): cards: hover/click/keyboard, scroll to the selected card,
      pan to its dot.
12. **W6** (built; check on a phone) Mobile bottom sheet, keyboard/a11y pass. Decided
    2026-11-25: below 700 px the sidebar is a bottom sheet with three
    heights (peek: handle + status line; half ~50%; full ~90%); tapping
    the handle steps peek -> half -> full -> peek; no dragging (rejected:
    drag + snap, more code, untestable headless; 2 heights). Focusing a
    route or clicking a dot raises it to at least half; focusing the
    search box raises it to full. Mine: it starts at half (the list
    shows on first load); the map's fit/pan leave room for the sheet.
    - Step 1 (done): `sheet.js` (pure): heights, next, raise, pixel height;
      `sheet` in the store.
    - Step 2 (done): the sheet's CSS, handle and wiring.
    - Step 3 (done): keyboard and screen readers: focus moves into the panel
      and back to the row, an `aria-live` announcement on focus change,
      visible focus rings, contrast, labels.

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
- **D4** (decided) Shapeless routes listed greyed. Rejected: omitted.
- **D5** (decided) Unmatched detours in `status.json` + a "Not on the
  map" section. Rejected: only a count in the status line.
- **D6** (decided) Ended detours shown in a collapsed "Ended" group at
  the bottom of the route panel. Rejected: hidden.
- **D7** (decided, done) `export site` replaced `export detours` in W2.
- **D8** (decided) Mode order metro, trolley, trackless, bus, rail; the
  faint network in one neutral grey (not route colors).
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

(Planned 2026-11-27 in `docs/hosting-plan.md`: option (1) below, with
GitHub Actions + Pages. Kept here for the history.)

Probably a spin-off that reuses this pipeline and contract. Cheapest
first: (1) static hosting + a scheduled job (every 5-10 min) running
`ingest -> match -> export site` and publishing `web/` (GTFS and the
24 MB street cache cached between runs, rebuilt rarely); (2) the same
plus a small proxy for live vehicles, if needed; (3) a real backend only
if those fall short. With plain overwrite, `web/data/` must be served
with short cache lifetimes (or revisit D3's build directories).

Caching (found 2026-11-26): `python -m http.server` sends no
`Cache-Control`, so the browser reused an old `routes/bus-49.json`
after a schema bump (Ctrl+Shift+R didn't clear it; a private window
did). Now `data.js` fetches with `cache: "no-cache"` (always revalidate;
a 304 when unchanged). For hosting, **versioned URLs** instead: fetch
`status.json` fresh, then every other file as `...?v=<generated_at>`,
so each export has its own URLs (nothing re-checked, old and new never
mixed, even mid-export) and the files can be cached long. The JS
modules themselves can still be cached stale (a page reading an old
`SCHEMA_VERSION`): versioned script URLs or a no-cache header on
`index.html` and `js/` cover that too.
