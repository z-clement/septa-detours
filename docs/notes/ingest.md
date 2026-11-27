# Notes: ingest and shared I/O (`ingest/`, `io.py`)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Atomic writes, the alerts fetch, and what the alerts API returns.
The OSM extract fetch is in `streets.md`.

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

## Snapshot store (`ingest/store.py`, hosting step 5, 2026-11-27)

Decided (me): **no checkout**. All 4 neighbouring local snapshot pairs
differ (even 40 minutes apart), so most 15-minute runs add a file
(~16 MB/day, ~6 GB/year of files): a checkout of the branch would
write all of them on every run. Instead, git commands directly:
`fetch --depth=1 --filter=blob:none` (the file list, no contents),
compare blob ids (a hash of the bytes), commit via a temporary index,
push. Planned in three increments: find the newest stored, commit,
fetch/push + CLI.

Done: `newest_stored(ls_tree)` (pure) over `git ls-tree -z <ref> --
alerts/` output -> `StoredSnapshot(name, blob)` or None (first run).
Only `blob` entries named exactly `<stamp>.json` count (a `README.md`
sorts after every stamp; a subdirectory is a `tree`). Its own name
pattern, `[0-9]` (match's `_SNAPSHOT_NAME` uses `\d`; ingest can't
import from match). Tests: `tests/test_ingest_store.py` (15; one input
is real git 2.56 output). Mutants: 11, 10 killed; `partition` ->
`rpartition` is equivalent (both reject every path that isn't
`alerts/<name>`).

Done: `commit_snapshot(snapshot, parent, repo)` -> commit id or None.
Adds `alerts/<name>` (mode 100644) to `parent`'s tree (None = root
commit, the orphan branch's first) in a temporary index
(`GIT_INDEX_FILE`), so the checkout, its index and every ref stay
untouched; moves no branch, pushes nothing. None when the blob equals
the newest stored one, or when the tree equals the parent's (same name
and bytes already stored, not the newest). Same bytes as an *older*
snapshot are stored (the feed went back). Same name, different bytes ->
`ValueError` (never replaces a stored snapshot); so does a non-stamp
name. Author/committer `github-actions[bot]` + its noreply address
(decided: the job's commits, not mine); message `alerts: <stamp>`.
`write-tree --missing-ok` + `GIT_NO_LAZY_FETCH=1` on every call: in the
job's partial clone the old blobs are absent and must stay so.
Finding: `commit-tree` ignores `commit.gpgSign` (only `git commit`
honours it), so `--no-gpg-sign` was a no-op and was dropped; a test with
`gpg.program=false` guards it. Tests: 12 more in
`tests/test_ingest_store.py` (real git in `tmp_path`, global/system
config off; bytes from real route fixtures), incl. a real
`--filter=blob:none --depth=1` clone where the old blob stays missing.
Mutants: 15, 14 killed; `GIT_NO_LAZY_FETCH` survives (a safety net
nothing trips today: without `--missing-ok` it's what fails the test).
