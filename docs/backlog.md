# Backlog

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Options and follow-ups not scheduled yet. The current plan is
`docs/web-plan.md`.

Other options, for later:
- **Settle parse's open questions** (each is my decision; ask):
  recurring windows ("7am - 4pm Mon thru Fri") and message-vs-API
  mismatches (route 44 #3, 61 #1): add an issue or not? Flagging makes
  many notices `partial` and changes the pinned `NOT_COMPLETE`.
  Detecting either means parsing message text, which `parse/` doesn't do
  yet. And a `kind` field (reroute / stop closure / relocation; route 6,
  9, BSO findings): changes `model.py`, so flag it first.
- **Keep collecting snapshots** (`uv run python -m septa_detours.ingest`);
  run parse + match over each and add fixtures for new quirks (then
  update all the pins listed above).
- **Small follow-ups**: move `alerts.make_client` to a shared
  `ingest/http.py` (OSM uses it too; its docstring says "SEPTA API");
  maybe make `write_bytes_atomic` a wrapper over `write_chunks_atomic`;
  maybe a byte-progress line for the OSM download.

Small follow-ups: plural "1 lines" in `export detours`' summary; a total
(`N placed of M detours`) needs a FeatureCollection extra member from
export.
