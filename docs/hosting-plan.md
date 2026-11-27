# Hosting plan: GitHub Actions + GitHub Pages (2026-11-27)

Written from the user's point of view: "I", "me", "my choice" = the
user. Replaces "Later: hosting with live fetching" in `docs/web-plan.md`
(option 1 there: static hosting + a scheduled job).

Status: **done and live** since 2026-11-27 at
https://z-clement.github.io/septa-detours/. Running it (what runs, where
to look, chores): `operating.md`. This file is the record of how it was
decided and built.

## Decided by the user (2026-11-27)

- **Repo**: published on my GitHub, public (free Pages needs public).
- **Host**: GitHub Actions builds the data; GitHub Pages serves `web/`.
- **Cadence**: every 15 minutes.
- **Domain**: the free `<user>.github.io/<repo>` address, not my own
  domain (nothing extra to secure).
- **Snapshots**: stored, somewhere durable (Claude recommended the
  branch below).
- **GTFS is fetched automatically** (changed 2026-11-27 after the terms
  check; at first it was to be a manual release asset like the street
  cache) from SEPTA's GitHub releases (`septadev/GTFS`; a new feed every
  2-4 weeks, published 2-6 days before it starts), choosing the newest
  release *in effect* (New York date), not "latest". Only
  `streets.parquet` is a manual release asset.
- **GTFS age warning: for me, not riders.** The job logs a warning as the
  feed nears its `feed_end_date`; the page says nothing (no contract
  change). Log only for now; opening an issue (which emails) can come
  later if I miss it.

## Facts measured (2026-11-27)

- One pipeline run locally: `ingest` ~1 s, `match` ~2 s, `export site`
  ~9 s (~350 MB RAM). Today's snapshot `134432Z`: 127 detours, 118
  matched to a route, 90 placed.
- `web/` is ~2.5 MB, of which `web/data/` is ~2.4 MB (187 files).
- A snapshot is ~130-210 KB of JSON (~17 KB gzipped). The API carries no
  fetch time inside, so an unchanged feed gives byte-identical files:
  two snapshots 40 minutes apart (`141550Z`, `145719Z`) differed in 1 of
  185 route entries.
- Inputs the job needs besides the alerts API: both GTFS feeds and the
  street cache
  (`streets.parquet`, 24 MB, built from ~540 MB of OSM extracts in
  ~30 s / ~1.2 GB RAM).

## Design

### The scheduled job (`.github/workflows/publish.yml`)

Every 15 minutes (`cron: "*/15 * * * *"`), plus a manual trigger:

1. Check out `main`; set up uv and Python 3.13; `uv sync`.
2. GTFS from SEPTA's releases (cached between runs); `streets.parquet`
   from the repo's `reference` release (public repo, so no token). Warn
   (a `::warning::` annotation in the run log) when either feed's
   `feed_end_date` is within 14 days or past; keep going either way, so
   the site never stops over old GTFS.
3. `ingest` -> `match` -> `export site`.
4. Store the snapshot (below).
5. Upload `web/` (without `web/test/`) and deploy it to Pages.

Failing safe: any failed step stops the run before the deploy, so the
last good site stays up. The page's "as of" time shows how old the data
is; step 4 below adds a visible warning when it's old.

### Reference data: a release asset (decided 2026-11-27)

`streets.parquet` (24 MB) changes rarely and is rebuilt by hand. It
lives as an asset of one GitHub release (tag `reference`), replaced by
hand after a refresh (`operating.md`). Assets aren't in git history, so
the "never commit raw downloads" rule holds. (GTFS was planned here too,
zipped by a `gtfs pack` command; replaced by `ingest gtfs`, above.)

Known limits of Actions timers: runs often start 5-15 minutes late
(sometimes skipped at busy times), and GitHub turns a scheduled
workflow off after 60 days with no repository activity. Whether commits
to the `snapshots` branch count is unclear; assume not, and re-enable
from the Actions tab if it stops.

### Snapshots: a `snapshots` branch (Claude's recommendation)

An orphan branch (no shared history with `main`) holding
`alerts/<stamp>.json`, plain JSON (not gzipped, so git can store
neighbouring snapshots as deltas). A snapshot is committed only when its
bytes differ from the newest one already stored, so a quiet feed adds
nothing. Pushed with the workflow's own `GITHUB_TOKEN` (`contents:
write`): no extra account or secret. Getting them locally: `git fetch
origin snapshots`.

Rejected: Actions artifacts (expire after 90 days), release assets
(clumsy for thousands of small files), cloud storage like S3/R2 (an
account and a secret to look after), a second repo (needs a token).

### Caching on Pages

Pages sends a fixed `Cache-Control: max-age=600` and can't be
configured. With plain overwrite a visitor could mix files from two
exports, or run old JS against new data. Fix (already planned, web plan
"Caching"): versioned URLs.

- Fetch `status.json` with `cache: "no-cache"`, then every other data
  file as `...?v=<generated_at>`.
- Version the JS modules too, so a returning visitor never runs old page
  code against a new `SCHEMA_VERSION` (how, without a build step, is
  settled in step 3).

## Steps (one increment each, tested and committed)

1. This plan.
2. **Versioned URLs** for data files and the JS modules. (Done
   2026-11-27: `data.js` `versioned`, `?v=<generated_at>`; `export
   deploy <out>` puts the code in `js-<hash>/`, `css-<hash>/`, hash of
   the code's contents, so data-only runs keep cached code.)
3. **Stale-data warning** on the page when the data is old (e.g. more
   than an hour: the job has stopped or is failing). (Done 2026-11-27:
   `format.staleNotice`, 1 hour (`STALE_AFTER_MS`, Claude's suggestion;
   change freely), from `snapshot_fetched_at`; an amber `#stale` banner
   at the bottom middle of the map, above the phone sheet; checked on the
   page's 1-minute tick.)
4. **Reference data** (done 2026-11-27): `ingest gtfs` + `gtfs
   unpack` for GTFS, the `reference` release for the street cache, and
   the GTFS end-date check (`gtfs/expiry.py`).
5. **Store snapshots** (done 2026-11-27): `ingest store`, which commits
   a snapshot to the `snapshots` branch only if it changed.
6. **The workflow** (done 2026-11-27): `publish.yml`, below, after the
   terms check (below) and a SEPTA credit on the page.
7. **My part** (done 2026-11-27): the repo, the `reference` release,
   Pages set to "GitHub Actions", the first runs.

## Terms checked before step 6 (Claude, 2026-11-27)

Read on 2026-11-27; quotes are from the pages themselves. Not legal
advice, just what the texts say.

- **SEPTA GTFS** (the license on <https://www3.septa.org/developer/>,
  agreed to when downloading): a "non-exclusive, limited and revocable
  right to use, reproduce and redistribute the Trip Planning Data", "as
  is"; no attribution required; "may not use SEPTA's trademarks and
  copyrighted materials for any commercial or profit-making use". So
  re-publishing GTFS as a release asset is allowed; the site is
  non-commercial.
- **SEPTA alerts API**: no terms found (the license covers GTFS only).
  15-minute polling is 96 requests a day.
- **SEPTA also publishes GTFS on GitHub**: `septadev/GTFS` releases,
  one `gtfs_public.zip` each; recent: `v202609271` (2026-10-06),
  `v202611010` (10-26), `v202611220` (11-18, ours). About every 2-4
  weeks, more often than "rarely".
- **OpenFreeMap** (<https://openfreemap.org/tos/>, updated 2026-11-24):
  public websites may integrate the service; free, "as-is", may be
  discontinued "at any time without notice"; forbids collecting data
  "in automated ways" (we don't: browsers load tiles as they view). The
  TileJSON's credit is `OpenFreeMap © OpenMapTiles Data from
  OpenStreetMap` (linked), shown by our compact `AttributionControl`.
- **OpenStreetMap** (OSMF attribution guidelines): credit "OpenStreetMap"
  and make the ODbL clear (a link to openstreetmap.org/copyright does).
  Visible at first, may collapse "on map interaction" or "automatically
  after five seconds": MapLibre 5.24.0's compact control starts open and
  collapses on the first drag. But `createMap` closed it at load (render
  sweep finding 6); fixed 2026-11-27: closed 5 s after load
  (`CREDITS_OPEN_MS`), with a SEPTA line first (`SEPTA_CREDIT`, "Detour
  data from SEPTA · Not affiliated with SEPTA", my choice). Checked
  headless (Brave + CDP): open at 2 s with all four links, closed at 8 s.
- **OSM data we publish ourselves**: `paths.geojson` (detour paths drawn
  along OSM ways) and the `streets.parquet` release asset are extracts
  of OSM. Republished every 15 minutes, they don't fit the "insubstantial"
  guideline (< 100 features, one-off; "repeated small extractions as one
  big extraction"), so treat both as ODbL: credit OpenStreetMap and say
  they're under the ODbL (the release description for `streets.parquet`;
  the page's existing credit for `paths.geojson`).

## The workflow as built (2026-11-27)

`.github/workflows/publish.yml`, one job, every 15 minutes + "Run
workflow"; `concurrency: publish` (no overlap, never cancelled);
permissions `contents: write`, `pages: write`, `id-token: write`;
`UV_NO_SYNC=1` so `uv run` uses `uv sync --locked --no-dev`'s env.

1. GTFS: restore the newest `gtfs-*` cache (by prefix); `ingest gtfs`
   (with `GITHUB_TOKEN`); after a `wrote`, delete older zips and save the
   cache as `gtfs-<file name>` (a new cache per SEPTA release, not per
   run). If the release list can't be fetched: `::warning::` and unpack
   the newest cached release (fails only with no cache). `gtfs unpack`,
   `gtfs check`.
2. `streets.parquet` from this repo's `reference` release (`curl`).
3. `ingest` -> `match` -> `export site` -> `export deploy _site` ->
   Pages (configure, upload, deploy).
4. After the deploy, `ingest store <snapshot>` with `continue-on-error`.

Step outputs reach shell scripts through `env:`, not `${{ }}` pasted
into them. Actions: `checkout@v7`, `cache@v6`, `configure-pages@v6`,
`upload-pages-artifact@v5`, `deploy-pages@v5` (major tags), and
`setup-uv@v10.3.3` (exact: setup-uv publishes no major tags since v8).
First run (2026-11-27) failed at the deploy with the first pins
(`deploy-pages@v4` from 2024, `upload-pages-artifact@v3`): "No artifacts
named github-pages were found", though the run *had* the artifact
(457 KB). Every action was 1-4 majors behind; all were updated
(checked: each tag exists; checkout v6+ still persists credentials,
now in a separate included file, which `ingest store`'s push uses).

Checked locally (Actions itself can't run here): the YAML parses
(`uvx --from pyyaml`); the GTFS and pipeline steps' shell, run with
`bash -eo pipefail` in a fresh clone: cache hit (no save key), empty
cache (download, stale zip deleted, `save_key=gtfs-gtfs_public-v202611220`),
API failure with cache (warning, exit 0) and without (exit 1); the
pipeline (~14 s, 131 detours, 199 files in `_site`); the store command
against a local bare origin (stored, then unchanged).

## Going live (done 2026-11-27)

Pushed; created the `reference` release with `streets.parquet` and its
ODbL notice; Settings -> Pages -> Source: "GitHub Actions"; the first
run by hand, then the schedule. The steps that recur (refreshing the
street cache) are in `operating.md`.

## Whole-project check (done 2026-11-27)

A pass over the whole repo after going live (Claude, with my decisions):

- The page, for riders: load errors in plain words (details in the
  console); the status line is "N detours as of <time>" (it said
  "N on the map", which overcounted); an open page offers a reload when
  newer detours are out (my choice: offer, don't force); the banners sit
  above the open credits; a favicon, a meta description, SRI hashes on
  MapLibre. Details: `notes/export-and-web.md`, "Public-facing pass".
- Code: ASCII-only digits in file-name patterns; package docstrings
  brought up to date.
- CI: a `test` workflow and Dependabot (`operating.md`).
- Docs: plans marked done, this file trimmed, `operating.md`, a README
  and an MIT LICENSE (data keeps its own terms: README).
- Decided to leave: routes H, L, R, XH unmatched (`backlog.md`); the
  screenshot script stays local (`tools/`, gitignored).

## After hosting

- **Targeted mobile UI/UX pass** (added 2026-11-27): once people try
  the hosted site, collect their feedback and do a phone-focused pass
  (`docs/ui-plan.md` was mostly checked on desktop plus a few phone
  renders). See `docs/backlog.md`.
