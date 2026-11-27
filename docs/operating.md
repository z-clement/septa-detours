# Operating the hosted site

The site, https://z-clement.github.io/septa-detours/, is rebuilt by
GitHub Actions every 15 minutes and served by GitHub Pages. How it came
to be (decisions, terms checked, the first runs): `hosting-plan.md`.

## What runs

- **`publish`** (`.github/workflows/publish.yml`), every 15 minutes and
  on "Run workflow":
  1. GTFS: restore the newest cached SEPTA release, `ingest gtfs` (a
     download only when the release in effect isn't the cached one),
     `gtfs unpack`, `gtfs check` (a `::warning::` within 14 days of a
     feed's end). If GitHub's release list can't be read, it warns and
     uses the cached release.
  2. `streets.parquet` from this repo's `reference` release.
  3. `ingest` -> `match` -> `export site` -> `export deploy _site` ->
     Pages.
  4. `ingest store`: the snapshot onto the `snapshots` branch, only if
     it changed. Allowed to fail (`continue-on-error`), so a git problem
     never keeps riders on old data.

  Any failed step before the deploy stops the run, and the last good
  site stays up.
- **`test`** (`.github/workflows/test.yml`), on every push to `main` and
  every pull request: ruff, pytest, `node --test web/test/*.test.js`.
- **Dependabot** (`.github/dependabot.yml`): one grouped pull request
  for action updates (weekly) and one for Python packages (monthly).
  Merge when `test` is green. `astral-sh/setup-uv` is pinned to an exact
  version (it publishes no major tags), in both workflows.

## Is it working?

- **The page** shows "N detours as of <time>". Over an hour old, an
  amber banner says so: the job has stopped or is failing.
- **Actions tab**: the `publish` runs. Scheduled runs often start 5-15
  minutes late, and GitHub skips some at busy times.
- **Snapshots**: the `store` step can fail without turning the run red.
  Check the branch still grows:
  `git fetch origin snapshots && git log -1 --format=%cd origin/snapshots`.
- **GTFS end dates**: warnings show as annotations on the run's summary.
  A new SEPTA release is picked up by itself once it's in effect.

## Fixing things

- **Re-run**: Actions -> publish -> "Run workflow" (branch `main`).
- **Schedule switched off**: GitHub disables a scheduled workflow after
  60 days without activity in the repo (the job's own snapshot pushes
  may not count). Actions -> publish -> "Enable workflow".
- **A failed step**: every step is a command you can run locally from
  the repo root (`CLAUDE.md`, "Commands"), against the same inputs.

## Routine chores

- **Refreshing the street cache** (occasionally; OSM changes slowly):
  1. `uv run python -m septa_detours.ingest osm` (~540 MB), then
     `uv run python -m septa_detours.streets` (~30 s, ~1.2 GB RAM).
  2. Check what it was built from:
     `uv run python -c "from septa_detours.streets.cache import read_street_cache_info as r; print(r())"`.
  3. On GitHub: Releases -> `reference` -> Edit. Delete
     `streets.parquet`, upload the new
     `data/processed/streets.parquet` (the website can't replace a file
     in place), and update the extract dates in the description, which
     must keep the ODbL notice:

     > `streets.parquet`: street data derived from OpenStreetMap,
     > © OpenStreetMap contributors, available under the Open Database
     > License (ODbL) 1.0: https://opendatacommons.org/licenses/odbl/1-0/
     > Built from Geofabrik extracts pennsylvania-, new-jersey- and
     > delaware-<YYMMDD> (<date>).

     The next run uses it.
- **Updating MapLibre** (`web/index.html`): the script and stylesheet
  carry `integrity` hashes, so a new version needs new ones (the command
  is in the comment there). Stay on v5 unless MapLibre is vendored
  (v6's worker can't load from a CDN).
- **Changing the data contract**: bump `SCHEMA_VERSION` in both
  `export/contract.py` and `web/js/data.js`. An open page with the old
  code is offered a reload, and an old cached page asks for one.

## Riders' side

An open page checks for newer detours every 5 minutes (and when its tab
is shown again) and offers a Reload button. It never reloads by itself.
Code is published under content-hashed folders (`js-<hash>/`), and data
files under `?v=<generated_at>`, so Pages' 10-minute cache never mixes
two versions.
