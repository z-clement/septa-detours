# Notes: GTFS reference data (`gtfs/`)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Loaders, shape coordinates, a route's shapes, directions.

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

Done: `gtfs/load.py::load_directions` (`DIRECTION_COLUMNS`: `route_id`,
`direction_id` Int8 like trips, `direction`, `direction_destination`).
Missing file -> `FileNotFoundError` (loud if SEPTA drops the extension).
Every trips `(route, direction_id)` is covered; no duplicates.
`tests/test_load_directions.py` (10, the first direct loader tests; real
rows under `tmp_path`, incl. a CRLF rail file).

Done (2026-11-25): `gtfs/load.py::load_feed_info` (`FEED_INFO_COLUMNS`:
`feed_version`, `feed_start_date`, `feed_end_date`, all strings; dates
are `YYYYMMDD`). Both real files have CRLF endings and say `v202611220`,
`20261122`-`20270220`. `feed_info.txt` is optional in GTFS: a missing
file raises `FileNotFoundError` and the caller decides (the export
records `null`). Used for `status.json`'s `gtfs` (decided: `feed_version`,
not file mtimes, which change on every copy). `tests/test_load_feed_info.py`
(7, real header and rows, CRLF).

Done (2026-11-27, hosting step 4): `gtfs/expiry.py::end_date_warning`
(pure; `today` passed in) and `python -m septa_detours.gtfs check`
(`gtfs/__main__.py::check_feeds`), for the hosted job. One line per feed:
`bus GTFS v202611220 ends 2027-02-20`, or `::warning::<message>` (an
Actions annotation) within `WARN_WITHIN_DAYS` = 14 days of
`feed_end_date` (inclusive: the end date is a service day, "ends
today"), past it, or when `feed_info.txt` is missing / lacks a column /
has no rows / has a blank or malformed date (exactly 8 ASCII digits and
a real day; `strptime` would take `2027220`). Always exits 0: old GTFS
must never stop the site. Each feed is loaded separately, so one broken
file doesn't hide the other. Tests: `tests/test_expiry.py` (18),
`tests/test_gtfs_main.py` (9); 25 mutants, all killed.

Done (2026-11-27, hosting step 4): `gtfs/pack.py::pack_gtfs` and
`python -m septa_detours.gtfs pack [out]` (default
`data/processed/gtfs.zip`). Decided (me): pack our own zip rather than
upload SEPTA's download as is; I upload it by hand on the GitHub website
(no `gh`). Members `bus/<table>.txt`, `rail/<table>.txt` (every `.txt`
directly in each feed directory, sorted; no subdirectories or stray
zips), so `unzip gtfs.zip -d data/gtfs` restores the layout. Byte-identical
for the same tables (fixed 1980-01-01 timestamps, mode 0644, sorted):
compare SHA-256 with the release asset to see if an upload is needed.
Each table is streamed in; the zip is built in memory, then
`write_bytes_atomic`. Missing or `.txt`-less feed directory ->
`FileNotFoundError`, exit 1, nothing written. Real feeds: 39 files,
26.4 MB, ~4 s; packing twice gave the same SHA-256, and `unzip` gave a
tree identical to `data/gtfs/`. Tests: `tests/test_gtfs_pack.py` (11);
17 mutants, all killed.
