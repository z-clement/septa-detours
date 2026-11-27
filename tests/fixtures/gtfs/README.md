# GTFS release fixtures

- `releases-2026-11-27.json`: SEPTA's GTFS releases, the newest 12, from
  `https://api.github.com/repos/septadev/GTFS/releases?per_page=12`
  (fetched 2026-11-27). Trimmed to the fields `ingest/gtfs.py` reads
  (`tag_name`, `draft`, `prerelease`, `published_at`, and each asset's
  `name`, `browser_download_url`, `size`, `digest`); values untouched, order kept
  (newest first, as the API returns them).
