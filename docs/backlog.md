# Backlog

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Options and follow-ups not scheduled yet. The plans (`web-plan.md`,
`geography-plan.md`, `ui-plan.md`, `hosting-plan.md`) are done; running
the hosted site is `operating.md`.

Other options, for later:
- **A targeted mobile UI/UX pass after hosting** (added 2026-11-27):
  once the site is live (`docs/hosting-plan.md`), people trying it on
  their phones will show what the desktop-led UI pass missed. Collect
  that feedback first, then plan the pass from it.
- **Settle parse's open questions** (each is my decision; ask):
  ~~recurring windows ("7am - 4pm Mon thru Fri")~~ (done 2026-11-26:
  `parse/hours.py`, UI plan U8) and message-vs-API mismatches (route
  44 #3, 61 #1): add an issue or not? Flagging makes
  many notices `partial` and changes the pinned `NOT_COMPLETE`.
  Detecting either means parsing message text, which `parse/` doesn't do
  yet. And a `kind` field (reroute / stop closure / relocation; route 6,
  9, BSO findings): changes `model.py`, so flag it first.
- **`source_key` collides for direction twins** (found in W5,
  2026-11-25; my decision): it hashes `(route_id, location_start,
  start)`, so route L1 OWL's EB and WB stop closures at 5th & Market
  (same place, same start) share `a08563ebaa011c5d` (1 pair in 134
  placed dots). The page tolerates it (selecting one highlights both;
  they share a dot), but the URL hash and card selection can't tell them
  apart. Options: add the raw direction to the hash (changes the pinned
  key `661b7024a25d2bbd` and every key across snapshots), or a
  page-side id (`source_key` + index). Parse stage + `model.py`: flag.
- **Use the collected snapshots**: the hosted job stores every changed
  snapshot on the `snapshots` branch (`git fetch origin snapshots`). Run
  parse + match over them and add fixtures for new quirks (then update
  all the pins listed in CLAUDE.md, "Testing habits").
- **Bus Revolution renames (H, L, R, XH)**: the alerts API still uses
  the old names and GTFS doesn't document the new ones, so these
  routes' detours stay "not matched to a route" (decided 2026-11-27:
  leave them until a trustworthy source for the mapping turns up;
  `match/routes.py`).
- **A `septa-detours` command** (`[project.scripts]`): one entry point
  instead of `python -m septa_detours.<stage>`. Not needed while the
  workflow calls the modules.
- **Small follow-ups**: move `alerts.make_client` to a shared
  `ingest/http.py` (OSM uses it too; its docstring says "SEPTA API");
  maybe make `write_bytes_atomic` a wrapper over `write_chunks_atomic`;
  maybe a byte-progress line for the OSM download.
