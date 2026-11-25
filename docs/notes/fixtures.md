# Notes: alert fixtures and real snapshots

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Which fixtures exist, why, and what reading every real detour showed.

Done: alert fixtures (chosen by Claude at my request, approved by me).
`tests/fixtures/alerts/`: 18 route entries from snapshot
`2026-11-25T025344Z`, named `<snapshot stamp>__<api route_id>.json`
(provenance-based; quirks live in the README, not the name). One file =
one whole route entry with its full `detour` list; tests pick items by
index. Copied with `jq` and checked equal to the source entry: decoded
values are identical, only formatting differs (the API's `\/` becomes
`/`). `README.md` holds the copy command and an index: one row per
interesting detour item (route, index, what makes it ugly, *expected*
result guessed before the parser exists). Parse tests are built from
those rows; challenge the guesses when writing them. Coverage includes
`bus_route_55` (clean baseline), `APP` and `trolley_route_15` (no
detours), and the Owl buses `rr_route_mfo`/`rr_route_bso` (`rr_` IDs and
rail-named modes, but buses).
Findings from reading all 140 detours:
- Stop entries come in three kinds: closures (route 6), prose closures
  where LS is the *replacement* stop and LE the closed one (route 9), and
  relocations (BSO "Clothespin stop"). Strengthens the `kind` question.
- Message text can contradict API fields (route 44 #3 "until 11/23" vs
  API end 11/24; route 61 #1 5:30pm vs 5:00 PM).
- Recurring windows ("7am - 4pm Mon thru Fri", "Monday thru Wednesday,
  7:00PM to 5:00AM") are common; the model can't represent them.
- "Trips Only" scoping (route 24 "Gloria Dei", route 68 "Express")
  affects only some trips: a `match/` problem.
- Direction can be missing (24 #1), repeated (24 #0 "NB Via ... Recover
  NB On"), spelled out at the end ("..., Eastbound"), or after the time
  ("Until 12/31/26 11:59pm SB,"). LS and LE can both be blank (64 #1, #2).

Done: second snapshot `2026-11-25T121123Z` (~9 h after the first, not a
day): 140 -> 166 detours. 5 removed, all already past their API `end`
(SEPTA removes promptly); 31 added, mostly Thanksgiving parade reroutes
for 11/26, posted ~14 h before they start (parse must not assume a
detour is active). No new direction spellings. Fixtures added:
`2026-11-25T121123Z__bus_route_31.json` and `__bus_route_124.json`; the
README now has one index table per snapshot. Findings:
- Same detour across snapshots: route 31 #2 is byte-identical in both
  route 31 fixtures (test `source_key` stability with it). Items 0-4 kept
  their indices; new items were appended (not guaranteed by SEPTA).
- Back-to-back phases: route 31 #3 ends 11/26 2:00 AM exactly when #5
  starts.
- Truncated LS `"Broad &"` (31 #6). Settled: parse/ flags it
  (`parse_location` rejects it; an unrecognized start location is an
  issue), so 31 #6 is `partial`.
- Doubled-dash date `"11-26--26"` pasted onto 7 routes; `"S PEnn Sq"`,
  `"Sping Garden"`; same place spelled `"30th & Chestnut Sts"` and
  `"30th & Chestnut"` (124 #0 vs #3).
