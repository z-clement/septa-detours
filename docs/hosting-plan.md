# Hosting plan: GitHub Actions + GitHub Pages (draft, 2026-11-27)

Written from the user's point of view: "I", "me", "my choice" = the
user. Replaces "Later: hosting with live fetching" in `docs/web-plan.md`
(option 1 there: static hosting + a scheduled job).

## Decided by the user (2026-11-27)

- **Repo**: published on my GitHub, public (free Pages needs public).
- **Host**: GitHub Actions builds the data; GitHub Pages serves `web/`.
- **Cadence**: every 15 minutes.
- **Domain**: the free `<user>.github.io/<repo>` address, not my own
  domain (nothing extra to secure).
- **Snapshots**: stored, somewhere durable (Claude recommended the
  branch below).
- **GTFS stays manual** (SEPTA's feeds change rarely): I download it as
  today. It and the street cache reach the job as release assets (below),
  not through the Actions cache. No `ingest gtfs` for now.
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
- Inputs the job needs besides the alerts API: both GTFS feeds (fetched
  by hand today; no ingest step) and the street cache
  (`streets.parquet`, 24 MB, built from ~540 MB of OSM extracts in
  ~30 s / ~1.2 GB RAM).

## Design

### The scheduled job (`.github/workflows/publish.yml`)

Every 15 minutes (`cron: "*/15 * * * *"`), plus a manual trigger:

1. Check out `main`; set up uv and Python 3.13; `uv sync`.
2. Download the reference data from the repo's `reference` release:
   `gtfs.zip` (both feeds) and `streets.parquet`. Public repo, so no
   token. Warn (a `::warning::` annotation in the run log) when either
   feed's `feed_end_date` is within 14 days or past; keep going either
   way, so the site never stops over old GTFS.
3. `ingest` -> `match` -> `export site`.
4. Store the snapshot (below).
5. Upload `web/` (without `web/test/`) and deploy it to Pages.

Failing safe: any failed step stops the run before the deploy, so the
last good site stays up. The page's "as of" time shows how old the data
is; step 4 below adds a visible warning when it's old.

### Reference data: release assets (decided 2026-11-27)

GTFS (~both feeds zipped) and `streets.parquet` (24 MB) change rarely
and are rebuilt by hand. They live as assets of one GitHub release
(tag `reference`), replaced in place (`gh release upload reference
<file> --clobber`) by a small upload script run after I refresh them.
Assets aren't in git history, so the "never commit raw downloads or
full GTFS" rule holds; it does republish SEPTA's public GTFS, so check
SEPTA's terms (step 6). Today's feeds: `v202611220`, running
2026-11-22 to 2027-02-20 (`feed_info.txt`, both feeds).

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
   than an hour: the job has stopped or is failing). Threshold: my
   decision.
4. **Reference data**: the upload script (zip both GTFS feeds + the
   street cache, upload to the `reference` release), the job's unpack
   step, and the GTFS end-date check (a small pure function, tested).
5. **Store snapshots**: a small script that commits a snapshot to the
   `snapshots` branch only if it changed.
6. **The workflow** (`publish.yml`) as above. Before it: check SEPTA's
   data terms (including republishing GTFS as a release asset) and
   OpenFreeMap's terms for a public site fetching every 15 minutes, and
   add a SEPTA credit to the page if needed.
7. **My part**: create the GitHub repo and push; create the
   `reference` release and run the upload script; Settings -> Pages ->
   Source: "GitHub Actions"; watch the first runs.

## After hosting

- **Targeted mobile UI/UX pass** (added 2026-11-27): once people try
  the hosted site, collect their feedback and do a phone-focused pass
  (`docs/ui-plan.md` was mostly checked on desktop plus a few phone
  renders). See `docs/backlog.md`.
