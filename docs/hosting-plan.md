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
- **Changed 2026-11-27 (after the terms check): GTFS is fetched
  automatically** from SEPTA's GitHub releases (`septadev/GTFS`; a new
  feed every 2-4 weeks, published 2-6 days before it starts), choosing
  the newest release *in effect* (New York date), not "latest". Only
  `streets.parquet` stays a manual release asset; `gtfs pack` became
  `gtfs unpack`. Was:
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
   than an hour: the job has stopped or is failing). (Done 2026-11-27:
   `format.staleNotice`, 1 hour (`STALE_AFTER_MS`, Claude's suggestion;
   change freely), from `snapshot_fetched_at`; an amber `#stale` banner
   at the bottom middle of the map, above the phone sheet; checked on the
   page's 1-minute tick.)
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

## Where we stopped (2026-11-27, end of session)

Done: steps 1-3 (this plan; versioned data and code URLs, `export
deploy`; the stale-data banner). Commits `3a912b1` .. `7fd2ab2`.

Next, in order:

1. **Me: put the repo on GitHub** (public), push `main`. Checked before
   pushing: 143 tracked files, 1.6 MB, no data or secrets in the tree or
   history (largest blob ever: `uv.lock`, 144 KB); `.gitignore` covers
   `data/raw/`, `data/gtfs/`, `data/processed/*`, `web/data/`, `.env`.
   Note: the commits' author email becomes public with the repo; if
   that's unwanted, set GitHub's noreply address (and decide whether to
   rewrite existing history) before the first push.
2. **Step 4, reference data**: done (2026-11-27).
   `python -m septa_detours.gtfs check` (end-date warnings as
   `::warning::` lines, always exit 0). GTFS (changed, see top):
   `ingest gtfs` (SEPTA's release in effect -> `data/raw/gtfs/`, size +
   SHA-256 checked, skipped if already saved) then `gtfs unpack`
   (-> `data/gtfs/`). `gtfs pack` was built, then removed. Decided: no
   upload script; I upload `streets.parquet` by hand on the GitHub
   website (instructions with the workflow, step 6).
3. **Step 5, snapshot store**: commit a snapshot to the orphan
   `snapshots` branch only when its bytes differ from the newest stored.
   Decided (2026-11-27): never check the branch out (it grows ~16 MB of
   files a day); git commands compare blob ids and commit through a
   temporary index (`ingest/store.py`, `docs/notes/ingest.md`).
   Done 2026-11-27: `python -m septa_detours.ingest store <snapshot>`
   (prints `stored ...` / `unchanged: ...`; exit 1 on a git failure,
   e.g. a lost race; never forces).
4. **Step 6, the workflow**: done 2026-11-27,
   `.github/workflows/publish.yml` (details below, "The workflow as
   built"). Terms checked first (section below); SEPTA credit added.
5. **Me: go live**: done 2026-11-27. Second manual run (after the
   action updates) green end to end: GTFS from cache, deploy, snapshot
   `2026-11-27T153734Z` stored by `github-actions[bot]`. Live at
   https://z-clement.github.io/septa-detours/ (`status.json` fresh,
   hashed `js-`/`css-` dirs, no `test/`, `Cache-Control: max-age=600`).
6. **My whole-project check** before announcing it (notes below), then
   share it and collect feedback for the mobile pass (`docs/backlog.md`).

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

## Going live (my steps, written by Claude 2026-11-27)

1. **Push**: `git push` (main).
2. **Create the `reference` release** (website): repo -> Releases ->
   "Draft a new release" -> "Choose a tag": type `reference`, "Create
   new tag: reference on publish" (target `main`). Title: `Reference
   data`. Description:

   > `streets.parquet`: street data derived from OpenStreetMap,
   > © OpenStreetMap contributors, available under the Open Database
   > License (ODbL) 1.0: https://opendatacommons.org/licenses/odbl/1-0/
   > Built from Geofabrik extracts pennsylvania-, new-jersey- and
   > delaware-261124 (2026-11-24).

   Attach `data/processed/streets.parquet` (24 MB). Publish (a draft's
   files can't be downloaded by the job). "Pre-release" off.
3. **Pages**: Settings -> Pages -> Build and deployment -> Source:
   "GitHub Actions".
4. **First run**: Actions -> publish -> "Run workflow" (branch `main`).
   Expect: green, GTFS downloaded (the first run has no cache), a
   snapshot stored, the site at `https://<user>.github.io/<repo>/`.
   Then let a scheduled run or two go by (they start late).
5. **Later, refreshing the street cache** (after `ingest osm` + `python
   -m septa_detours.streets`): edit the release, delete
   `streets.parquet`, upload the new one (the website can't replace in
   place), update the extract dates in the description.

## Notes for the pre-deploy check (collected by Claude, 2026-11-27)

Minor things noticed along the way, for the whole-project check before
the first deploy. None blocks hosting; each is a small decision.

- **CLAUDE.md "Current state" is out of date**: it says contract
  **schema 9** (it's 10 since `e8a619d`) and ~1660 Python / ~156 JS
  tests (now 1691 / 172).
- **Error messages are written for me, not riders**: a missing data file
  shows "Make it first: uv run python -m septa_detours.match ..." and a
  schema mismatch "Re-export the data (or reload the page)" in the red
  `#error` banner (`web/js/data.js`). On the public site a rider would
  see these. Maybe a rider-facing line ("Detours couldn't load; try
  again later") with the details in the console.
- **`#error` banner placement**: centered on the whole window (sidebar
  included) and at the top, where on narrow screens it sits under the
  map key / zoom buttons. `#stale` had the same problem and moved to the
  bottom middle of the map; `#error` could follow (it would only meet
  `#stale` if both show, which can't happen today).
- **No favicon**: every load asks for `/favicon.ico` (404). A small icon
  (or `<link rel="icon" href="data:,">` to stop the request).
- **MapLibre from unpkg** (`index.html`, pinned 5.24.0) with no
  `integrity` attribute: if unpkg served a different file, the page
  would run it. Add SRI hashes, or copy MapLibre into `web/vendor/`
  (it'd then be versioned by `deploy` too, if under `js/`).
- **An open tab never sees new data**: the page loads the data once;
  after an hour the stale banner asks for a reload. Later, maybe: re-check
  `status.json` every few minutes and offer "New detours: reload".
- **`docs/web-plan.md` "Caching"** describes the plan before it was built
  (and suggested a commit-based version; it's content-based). History
  only; fine to leave or trim.
- **The headless screenshot script isn't in the repo**: it lived in
  Claude's scratchpad and was lost twice (rewritten 2026-11-27 as a
  ~30-line CDP script). If headless checks stay useful, keep a copy in
  e.g. `tools/` (Node 20, `--experimental-websocket`, no dependencies).
- **`#stale` covers the open credits** (found 2026-11-27, headless
  1200x800): while the credits are open (the first 5 s), the amber
  banner's second line sits behind the credits strip. Only when the data
  is old. Raise `#stale` a little, or accept it.
- **Public-facing text to review**: the page title, the status line's
  wording ("28 without a location, 9 not matched to a route" reads as
  internal), and a SEPTA credit / "not affiliated with SEPTA" line
  (step 6).

## After hosting

- **Targeted mobile UI/UX pass** (added 2026-11-27): once people try
  the hosted site, collect their feedback and do a phone-focused pass
  (`docs/ui-plan.md` was mostly checked on desktop plus a few phone
  renders). See `docs/backlog.md`.
