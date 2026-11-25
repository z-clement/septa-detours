# Notes: OSM street data (`ingest osm`, `streets/`)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Geofabrik extracts, reading/clipping them, the Parquet street cache.

OSM street data (done, this session; all written by Claude in reviewed
increments). Decided (my choices): **OSM** over city centerlines;
**Geofabrik** extracts over Overpass (the public Overpass server
refused even small test queries "at capacity" and asks bulk/automated
users to self-host); a **Parquet cache** rebuilt by hand only when the
extracts are refreshed (bus routes change rarely, so not every run);
**hand-written `.osm` XML** test fixtures.
- `io.py::write_chunks_atomic(chunks, path)`: streaming twin of
  `write_bytes_atomic`. Chunks go straight to `<name>.tmp` (never joined
  in memory), `replace` only after the iterator is exhausted, so a
  wrapper that raises after the last chunk (checksum) leaves the old file.
  Opens `"wb"`: a stale `.tmp` from a `kill -9` is overwritten.
- `ingest/osm.py`: `GEOFABRIK_REGIONS = ("pennsylvania", "new-jersey",
  "delaware")` (bus stops reach Trenton TC and Claymont TC).
  `extract_url(region)` -> `.../north-america/us/<region>-latest.osm.pbf`
  (region must fullmatch lowercase hyphenated words; reject, don't
  sanitize). `dated_extract_name(region, final_url)`: the whole
  redirect target must be `.../us/<region>/<region>-YYMMDD.osm.pbf`
  (real-date check via `strptime("%y%m%d")`, decided by me); anything
  else raises (no redirect would lose the data date).
  `parse_md5_file(content, expected_name)`: strict `md5sum` line
  (lowercase hex, two spaces, optional final `\n`; CRLF, `*name`, extra
  lines -> "not one md5sum line"); the name must match (`-latest.md5`
  names a different file). `fetch_extract(client, region, root)`:
  stream `-latest` -> dated name from `response.url` -> GET the *dated*
  `.md5` **before reading the body** (decided by me: fail fast) -> stream
  `iter_bytes()` (decoded, since the MD5 is of the file) through
  `_verified_chunks` into `write_chunks_atomic`. Any failure before the
  body writes nothing, not even the directory.
- `ingest/__main__.py`: optional positional `source` (`alerts` default,
  or `osm`). `osm` fetches every region, **continues past a failed one**
  (decided by me) and exits 1 with `error: N of 3 regions failed: ...`;
  `fetching <region> (<url>)` on stderr, `wrote <path>` on stdout. httpx
  status errors print two lines (they include an MDN link).
- `streets/load.py::read_street_ways(path, bbox=None)`: one row per way
  with a `name` and a `highway` in `ROAD_TYPES` (motorway..residential,
  `_link`s, living_street, service, busway; no footway/path/cycleway/
  steps/track/construction/proposed). `STREET_WAYS_SCHEMA`: `way_id`
  Int64, `name` (exact OSM text), `highway`, `node_ids` List(Int64),
  `coordinates` List(List(Float64)) `[lon, lat]`. File order; relations
  skipped. A kept way with a location-less node raises (Geofabrik
  extracts have none). `bbox = (west, south, east, north)`: keep a way if
  any node is inside (edges inclusive); the whole way is kept.
- `streets/cache.py`: `combine_street_ways(frames)` (concat, collapse
  rows identical in every column to first appearance; the same `way_id`
  with different content raises "re-fetch the extracts": 612 real border
  ways, all identical). `service_bbox(stops, margin_m=2000)` (stop extent
  plus a margin that is **at least** `margin_m` on WGS84: 110,574 m/deg
  lat, 111,320 x cos(lat at the edge furthest from the equator) for lon;
  tests measure with WGS84 formulas, since a mean-radius haversine is
  0.25% off at 40 N). `write_street_cache(ways, StreetCacheInfo(sources,
  bbox), path)` (exact schema + unique `way_id` or `ValueError`; Parquet
  built in memory then `write_bytes_atomic`; provenance as JSON in
  Parquet key-value metadata `septa_detours:sources` / `:bbox`).
  `read_street_cache` / `read_street_cache_info` (missing file ->
  `FileNotFoundError` naming `BUILD_COMMAND`; wrong schema -> "rebuild";
  malformed metadata -> `ValueError`). `find_latest_extract(region,
  root)`: regex fullmatch `<region>-\d{6}.osm.pbf` (so `new` can't match
  `new-jersey`, `.tmp`/`-latest` ignored), newest by name; none ->
  `FileNotFoundError` naming `FETCH_COMMAND`. `DEFAULT_OSM_DIR` is
  duplicated from `ingest/osm.py` on purpose (`streets/` never imports a
  stage; only `__main__` glue imports `GEOFABRIK_REGIONS`).
- `streets/__main__.py`: find all extracts first (a **missing region
  fails**, decided by me), then stops -> bbox -> read each (progress on
  stderr) -> combine -> write. `FileNotFoundError`/`ValueError` -> exit 1;
  a corrupt `.pbf` (pyosmium `RuntimeError`) keeps its traceback.
- `gtfs/load.py::load_stops` (`stop_id`, `stop_name`, Float64 lat/lon,
  `feed`). Keeps the 478 bus rows with null coordinates (GTFS
  `location_type` 3/4 station nodes); `location_type` isn't loaded (rail
  lacks it).
Tests: `test_io.py`, `test_ingest_osm.py` (fake Geofabrik via
`MockTransport` serving the real 301 -> 307 -> dated chain; a logged body
stream proves the `.md5` is fetched before any body byte is read),
`test_streets_load.py` (fixture `tests/fixtures/osm/broad_washington.osm`,
each way annotated with the rule it tests), `test_streets_cache.py`,
`test_streets_main.py` (fake repo; `.pbf` files converted from XML with
`osmium.SimpleWriter(..., overwrite=True)`), `test_load_stops.py`. Every
increment mutation-checked; survivors were either fixed with a new test
or are documented equivalents. 760 tests total.
Real numbers (2026-11-24 extracts): PA read ~25 s / 1.2 GB peak; cache
146,871 ways, 24 MB; bbox `(-75.858, 39.652, -74.730, 40.352)`.
Stop-name probe (scratch, not committed): matching `location_start`
against bus stop names ("A & B", case/dot/suffix-insensitive, either
order) located 118 of 166 notices within ~300 m; misses were typos,
intersections with no stop (JFK & Broad), and non-intersections.
