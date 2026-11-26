# Notes: shared models (`model.py`)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Later model changes (locations, `StartPoint`, `dump_detours`) are in
`parse.md`, `match.md` and `export-and-web.md`.

Done: `model.py` (written by Claude at my request). All models share a
`_Frozen` base: `frozen=True, extra="forbid", strict=True`.
- `SourceText`: the nine raw API strings verbatim + snapshot file name
  (a name, not a path).
- `DetourNotice` (parse output): `source`, `source_key` (hash of
  normalized `(route_id, location_start, start)`; not an identity),
  `start`/`end: AwareDatetime | None`, cleaned `location_start`,
  `location_end`, `reason`, `direction`, `issues`. `None` = couldn't
  determine; the why goes in `issues`.
- `Detour` = `notice` + `match: RouteMatch | None` (None = match failed;
  no "not attempted" state) + its own match `issues`. `RouteMatch` has
  `feed`, GTFS `route_id`, `shapes: tuple[AffectedShape, ...]`
  (`shape_id`, `direction_id`). No detour path geometry yet.
Decisions:
- One API `detour` list entry = one `DetourNotice` (45 of 57 routes had
  several). The raw API shape is parse's private model, not in `model.py`.
- `status` is a plain `@property`, not `computed_field`: a computed field
  is dumped to JSON and `extra="forbid"` then rejects it on reload.
  `unknown` = no `location_start`, or neither `start` nor `end`;
  `complete` = start, end, location_start, direction all known and no
  issues (`location_end`/`reason` optional); else `partial`.
- `CleanText` (pattern `^\S(?:.*\S)?$`): parsed text must be stripped and
  non-empty; blank -> `None`. Inner whitespace is allowed.
- `Direction` = NB/SB/EB/WB only. Real messages also say "Eastbound",
  "W/B"; parse normalizes. No inbound/both seen.
- `direction_id` is strict `int` with `ge=0, le=1`, not `Literal[0, 1]`
  (Literal accepts `True` and `1.0` even in strict mode).
- `start`/`end` only need *a* zone; choosing America/New_York is parse's
  job, and so is flagging `end < start` as an issue.
Tests: `tests/test_model.py` (35; `make_notice(**overrides)` over a real
route 2 entry). 15 mutations, all caught. 185 tests total.

## Tier B fields (2026-11-25)

`Step` (`turn`: via/left/right, `street` as written) and
`DetourNotice.route_steps` (default `()`); `RouteMatch.rejoin_point`
(a `StartPoint`, default `None`) and `RouteMatch.skipped`
(`SkippedStretch`: `shape_id` + `(lon, lat)` line, at least 2 points,
bounded; default `None`). Defaults keep pre-tier-B files readable (a
test reads one). Bounds can't catch a lat/lon swap in Philly (-75 is a
valid latitude): the realistic-coordinate tests in `match/` do.

## Tier C field (2026-11-26)

`RouteMatch.path`: the detour's own line, `(lon, lat)` points in travel
order, at least 2, bounded like `SkippedStretch.line`; default `None`
(a test reads a pre-tier-C file). A plain tuple, not a model: unlike a
stretch, it isn't cut from one shape, so there's nothing to name with
it. `rejoin_point`'s docstring now says it may come from the walk (a
rejoin tier B couldn't find).
