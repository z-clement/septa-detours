# Notes: parse stage (`parse/`)

Moved verbatim from CLAUDE.md on 2026-11-25. Written from the user's
point of view: "I", "me", "my choice" = the user. Line-level details
may be out of date; the code and tests are the source of truth.

Snapshot bytes -> `list[DetourNotice]`: text, times, directions,
source keys, the raw API model, notices, locations.

Done: `parse/` skeleton (scaffolded by Claude at my request). Every function raises `NotImplementedError`; ruff,
ty and imports pass. Layout:
- `_api.py`: private raw models `ApiRoute` (`route_id`, `mode`,
  `detour`) / `ApiDetour` (the six strings), `extra="ignore"` (outside
  format; unlike `model.py`'s `forbid`), strict, frozen.
  `read_snapshot(content: bytes) -> list[ApiRoute]`: **done** (see
  below). A structural error fails the whole snapshot
  (`ValidationError`): API drift should be loud, not skipped.
- `text.py::clean_text(raw) -> str | None`: **done** (see below).
- `times.py::parse_api_datetime(raw) -> datetime` and
  `local_time_issue(moment) -> str | None`: **done** (see below).
- `direction.py`: `normalize_direction(token) -> Direction | None` and
  `find_directions(message) -> tuple[Direction, ...]`: **done** (see
  below). Finding is separate from deciding.
- `notice.py`: `make_source_key(route_id, location_start, start) -> str`,
  `parse_detour(route, detour, snapshot) -> DetourNotice`,
  `parse_snapshot(content, snapshot) -> list[DetourNotice]`: all
  **done** (see below).
Decisions:
- Field parsers raise `ValueError` with a reason; only `parse_detour`
  catches, turning it into `None` + an issue prefixed with the field name
  (`"start: ..."`). Messy text never raises out of `parse_detour`; bugs
  (e.g. a `CleanText` violation) still do.
- Directions: exactly one distinct -> it; none or 2+ different ->
  `None` + issue. Never pick one.
- `end` < `start` -> keep both, add an issue. API `start`/`end` win over
  times in the message text.
Open (in `parse_detour`'s docstring; still undecided, see `../backlog.md`):
- Whether recurring windows and message/API mismatches add an issue
  (adding one makes most notices `partial`).
- A `kind` field (reroute / stop closure / relocation) would change
  `model.py`: flag it before changing.

Done: `parse/text.py::clean_text` = `" ".join(raw.split()) or None`.
Decided: inner whitespace runs collapse to one space (typing slips in 9
fixture values; match/ compares street names; `SourceText` keeps the
original). No-arg `split()` covers all Unicode whitespace incl. NBSP,
the same set `CleanText`'s `\S` rejects, so output always validates.
Never raises. `tests/conftest.py` holds the fixture loaders (pytest
fixtures, since `tests/` has no `__init__.py`): `read_alert_fixture`
(full file name -> bytes) and `alert_fixture_names` (sorted `*.json`).
`tests/test_text.py` (18) includes a sweep validating every fixture
location/reason against the real `CleanText`; 8 mutations, all caught.
Write NBSP in tests as `"\u00a0"` (RUF001).

Done: `parse/times.py`. `parse_api_datetime`: `clean_text` (blank ->
`ValueError("blank datetime '...'")`), then `strptime` with
`API_DATETIME_FORMAT = "%m/%d/%Y %I:%M %p"` (leading zeros optional, any
case of AM/PM; all 108 fixture values fit), then
`.replace(tzinfo=SEPTA_ZONE)`. Failure -> `ValueError("unrecognized
datetime '...'")` `from None`; messages quote `raw` as sent. Needs
`# noqa: DTZ007` (zone attached on the next line). Never
`naive.astimezone(zone)`: it reads naive as the *machine's* zone and
passes only on an Eastern machine (a `TZ=UTC` + `time.tzset()` test
guards it). `strptime` already treats a format space as `\s+`, so
`clean_text` is redundant there but kept to state the rule explicitly.
Decided DST (option C): accept, don't raise. `strptime` gives `fold=0`,
so a fall-back 1:xx reads as EDT; a spring-forward 2:xx keeps the
pre-change offset (= 3:xx EDT). Separate pure
`local_time_issue(moment) -> str | None` flags it: gap = wall time
changes on a UTC round trip (checked first, since in a gap flipping
`fold` also changes the offset, PEP 495); overlap = flipping `fold`
changes `utcoffset()`. Uses `moment.tzinfo` (fixed offsets never
flagged); naive -> `ValueError`. Messages: `"nonexistent local time
2027-03-14 02:30 (DST gap); read as 03:30 EDT"`, `"ambiguous local time
2027-11-07 01:30 (DST overlap); read as EDT"`. **`parse_detour` must call
it for start and end** and add the result (field-prefixed) to `issues`.
Python gotcha: aware datetimes with the *same* `tzinfo` compare by wall
time, ignoring offset and `fold`. Harmless now (we never make `fold=1`),
but `parse_detour`'s `end < start` check compares wall clocks; use
`.astimezone(UTC)` if that ever matters. `tests/test_times.py` (53);
20 mutations, 17 caught, 3 equivalent (cached `ZoneInfo` is the same
object; `raw.strip()` vs `clean_text`; `resolved != moment`). The
reusable mutation runner is a scratch script (not committed): copy the
file, apply `[old, new]` pairs that must each match once, run pytest
with `PYTHONDONTWRITEBYTECODE=1`, restore in `finally`. 256 tests total.

Done: `parse/direction.py`.
- `normalize_direction(token)`: lookup in `_SPELLINGS` (12 entries,
  written out one by one, keyed casefolded) on `token.casefold()`.
  Decided: **case ignored** (my choice). Each pattern covers all four
  directions: `NB`, `N/B`, `Northbound` (seen so far: `NB SB EB WB`,
  `W/B` once, `Eastbound`/`Westbound`). Nothing else forgiven: `"SB,"`,
  `" NB"`, `"Webster"`, `"N.B."`, `"W / B"`, `"inbound"` -> `None`.
  Stripping punctuation is the tokenizer's job.
- `find_directions(message)`: split on `_TOKEN_SEPARATOR =
  r"[^\w/]+"` (every char but letters, digits, `_`, `/`), normalize each
  token, dedupe in first-appearance order with `dict.fromkeys`. `/` stays
  inside tokens so `W/B` survives; dates and `Tower/Manor` become harmless
  tokens. Known gaps, safe (no direction -> issue later): `"NB/SB"` is one
  token (not seen; pinned by a test); a direction glued to digits or
  letters (`11:59pmSB`) isn't found.
On all 157 distinct real messages (both snapshots): 151 give one
direction, 6 give none (5 "Discontinued Transit Stop" + route 24 #1),
none give two different ones; ignoring case added no surprise matches.
`tests/test_direction.py` (78): spellings, case, rejections, a
fixture-driven `(stamp, route_id, index, expected)` table, hand-built
order/dedupe/punctuation cases. Mutations: 15 + 10; 2 survivors, both
equivalent (`.lower()` vs `.casefold()` on ASCII keys; dropping `+` from
the separator only adds empty tokens, which normalize to `None`).
334 tests total.

Done: `parse/notice.py::make_source_key`. Decided (my choice):
whitespace + case. Each field -> `(clean_text(raw) or "").casefold()`;
blank and whitespace-only both hash as `""`; inner runs collapse to one
space (not removed). Nothing else forgiven: `"3:00"` != `"03:00"`. The
three fields are hashed as `json.dumps([...])` (no separator character,
so text can't shift between fields and collide), UTF-8, `sha256`, first
`SOURCE_KEY_LENGTH = 16` hex chars. `tests/test_notice.py` (24) includes
a **pinned value** (`661b7024a25d2bbd` for route 31 #4): keys are compared
across snapshots parsed at different times, so changing the algorithm
must be deliberate. Route 31 items 0-4 get equal keys across both
snapshots (they're byte-identical, so the fixtures can't distinguish
normalizations; hand-built tests do). 15 mutations, 13 caught; 2
survivors only matter for non-ASCII input (none in fixture key fields):
`.lower()` vs `.casefold()`, `ensure_ascii=False`.

Done: `parse/_api.py::read_snapshot`: module-level
`_SNAPSHOT = TypeAdapter(Annotated[list[ApiRoute], Field(min_length=1)])`,
then `_SNAPSHOT.validate_json(content)`. Everything bad is a
`ValidationError`: invalid JSON, invalid UTF-8, a BOM, trailing garbage,
non-list top level, null/missing/wrong-type fields at either level.
Decided (my choice): **`[]` is rejected** (real snapshots list all ~185
routes, even detour-less ones; `[]` would read as "no detours anywhere");
**duplicate `route_id`s not checked** (not a shape problem; none seen).
Values are verbatim (the API's `\/` decodes to `/`; no cleaning).
Checked by hand: both real snapshots have 185 entries, no BOM, all six
detour keys present and all strings. `tests/test_api.py` (36): every
fixture wrapped as `b"[" + bytes + b"]"` and compared field by field to
the decoded JSON; `make_entry`/`make_detour(**overrides)` helpers; a
25-case rejection table. 11 mutations, 10 caught; `strict=False`
survives and is equivalent for JSON input (lax JSON mode doesn't coerce
numbers/bools/arrays to `str` or strings/objects to `tuple`). Strict
does bite in Python: `ApiRoute(**dict)` with a list of dicts fails, so
tests compare against `read_snapshot(...)` output instead. 394 tests
total.

Claude habit to watch: it has twice typed literal NBSPs into test
strings. Ruff RUF001 catches it; fix with `sed -i
's/\xc2\xa0/\\u00a0/g' <file>` (Edit can't match the invisible char).

Done: `parse/notice.py::parse_detour` and `parse_snapshot` (written by
Claude in four increments, each reviewed). `parse_detour`:
- `source` = `SourceText` with the raw strings verbatim; `source_key` =
  `make_source_key` on the *raw* `(route_id, location_start, start)`.
- `location_start`/`location_end`/`reason`: `clean_text`. Decided (my
  choice): blank -> `None` with **no issue** (a `None` location_start
  already makes `status` `unknown`; blank LE/reason are normal). So an
  `unknown` notice can have empty `issues`: consumers must check
  `status`, not just `issues`.
- Private `_parse_time(field, raw) -> (datetime | None, issues)`: catches
  `ValueError` -> `"start: unrecognized datetime '...'"` /
  `"end: blank datetime ''"` (the parser's message, field-prefixed); a
  parsed value keeps any `local_time_issue` as `"start: nonexistent
  local time ..."` / `"end: ambiguous local time ..."`.
- Private `_is_before(later, earlier)`: compares **instants**
  (`.astimezone(UTC)`), not wall clocks: in a DST gap they disagree
  (start 3/14/2027 2:30 AM = 07:30 UTC is after end 3:10 AM = 07:10 UTC).
  Strictly before only; equal start/end is not flagged. Issue: `"end:
  before start"`. Skipped if either time is `None`.
- Private `_pick_direction(message)`: one distinct -> it; none ->
  `"direction: none found in message"`; 2+ -> `"direction: conflicting
  SB, NB in message"` (message order). No real message conflicts yet.
- Issue order (documented): start, end, order check, location_start
  (added later, see "Locations"), direction.
`parse_snapshot` = `[parse_detour(route, d, snapshot) for route in
read_snapshot(content) for d in route.detour]`; catches nothing (a
structural `ValidationError` fails the whole snapshot).
Tests in `tests/test_notice.py`: helpers `load_route` (fixture ->
`ApiRoute` via wrapped `read_snapshot`), `parse_fixture_item`,
`make_api_detour(**overrides)`/`parse_made` (route 55 #0's raw strings;
used for bad times, DST, conflicts: no fixture has those), and
`mini_snapshot` (fixtures joined into one API list, deliberately
unsorted: 55, APP, 64, trolley 15, 24). Route 55 #0 is compared as one
whole hand-written notice. Fixture sweep: all **65** fixture items parse
and JSON round-trip; a pinned `NOT_COMPLETE` dict lists every
non-complete item with its issues (now 10, see "Locations"; was 4: 24
#1, 6 #0 no direction; 64 #1, #2 unknown, no issues). **Adding a fixture
breaks the pin on purpose**: review its items, then update the count
and `NOT_COMPLETE`. Mutations: 19 + 14 + 10 + 5 (sweep) + 6, all caught
except equivalents (`directions[0]` vs `[-1]` when len is 1). Bad-time
handling is covered only by hand-built tests (the sweep can't see it).
428 tests total.
Real snapshots, by hand (before locations were parsed): `025344Z` 140
notices (131 complete, 7 partial, 2 unknown); `121123Z` 166 (157 / 7 /
2). Every partial was "direction: none found"; every unknown is route
64's blank-LS items. Current numbers: see "Locations".
README "Expected" guesses held, except the ones that hinge on open
questions (recurrence / mismatch issues are not added, so route 2 #0,
32 #2, 44 #3 are `complete`). Route 24 has 4 items, not 3.

Done: locations, `parse/location.py` + `model.py` (written by Claude in
reviewed increments). Decided (mine): splitting lives in **parse/** with
a model field (not private to match/); recognize **intersection +
segment** forms first; only an **unrecognized start location** is an
issue (end text can be inferred by walking the detour).
- `model.py`: `Intersection(streets: (A, B))`, `Segment(street,
  between: (B, C))`, each with a fixed `kind` literal; `type Location`
  is discriminated by `kind` (JSON without a valid `kind` is rejected).
  Names are `CleanText`, kept as written (not normalized: that's
  match/streets). `DetourNotice` gained **required** `start_place` /
  `end_place: Location | None` (decided: no default). `status` unchanged.
- `parse_location(raw) -> Location`, raises `ValueError` quoting `raw`:
  `"A & B"` / `"A and B"` (any case, `&` spacing optional); `"A
  btwn|btw|between B & C"` (whole word, any case). A final plural
  `Sts`/`Aves`/`Streets` goes onto both names of the pair, singular
  (`Arch & 15th Sts` -> `Arch St`, `15th St`; in a segment only onto B
  and C). Unrecognized: blank, not exactly two names (`Broad &`,
  `Dickinson`), two markers, `&` before the marker, any `/`, `to`, `at`.
  **Same street twice** raises too (decided by Claude: `Ridge Ave & Ridge
  Ave` would make every joint between two Ridge Avenue ways a candidate;
  also a segment bounded by its own street). Bounds keep text order. Known
  limit: `Arch St & 15th Sts` gives `Arch St St` (none seen; the match
  just fails). Private `_split_pair` is shared by both forms.
- `parse_detour`: private `_parse_place(field, raw)`; blank -> `None`,
  no issue; start unrecognized -> `None` + `"location_start:
  unrecognized location '...'"`; end unrecognized -> `None`, issue
  dropped. Issue order: start, end, order check, location_start,
  direction.
- Real snapshots now: `025344Z` 140 (120 complete / 18 partial / 2
  unknown); `121123Z` 166 (145 / 19 / 2). 160 of 172 location strings
  parse (136 intersections, 23 segments); 21 and 50 notices have end text
  that didn't parse (29 are the parade's `JFK btwn 20th & 15th/ Art
  Museum 16th`). Start-location issues: `PNC Center` x6, `Ridge Ave &
  Ridge Ave` x2, `Bethayres Station`, `Dickinson`, `University Ave at The
  VA Hospital`, `Chester Pk/Morton Ave & 9th St`, `Broad &`.
- Tests: `tests/test_location.py` (fixture sweep pins the 7 unparsed
  fixture locations), location tests in `test_model.py`/`test_notice.py`.
  The `NOT_COMPLETE` pin is now 10 (added: 49 #2, 61 #0/#1, 68 #0/#1,
  31 #6, and 24 #1 gained a location issue). `test_match_notice.py`'s
  parse-issues test now expects 24 #1's location issue too. Every
  increment mutation-checked; the one survivor is equivalent. 969 tests
  total.
- Not updated yet: the fixture README's "Expected" column for the
  location-related items.

## Route steps (tier B, 2026-11-25)

`parse/steps.py::parse_route_steps(message) -> tuple[Step, ...]`: the
street after the first `via` (also glued: `viaTasker`), then each turn
(`Left on` / `Right on`, or `L -` / `R--`), up to the first `Reg Rt` /
`Reg Rte` after it. Commas inside a step and parenthesized asides are
dropped, a leading dash stripped; a street must be plain words, at most
4 (`Cecil B Moore Ave`), without `on` or `around`. Anything else raises.
`parse_detour` stores it as `DetourNotice.route_steps`, `()` with no
issue when it raises. Real: 107 of 157 distinct messages. Tests
(`test_steps.py`, real messages verbatim + hand-built edges); mutation
survivors were either equivalent (`-+` vs `-`, the lstrip handles the
rest) or dead code, removed (`not words`, an en dash nobody writes,
stop words no test needed).

## Daily hours (UI plan U8, 2026-11-26)

`parse/hours.py`: `parse_daily_hours(message)` -> `DailyHours | None`,
or `ValueError` for hours it can't read. Reads only the text before
`via`; date labels (`on Thurs 11/26/26`) go *before* commas become
spaces (`Mon thru Fri, 12/26/26`: the comma shows `Fri` ends the range:
a sweep bug, now a test). Daily = a time range plus days or `until`
(every day); a range on one date isn't (start/end cover it). Times need
am/pm or an unambiguous 24-hour `h:mm` (`00:30`, `23:30`); `11:59`,
`12:30` with no am/pm raise ("morning or evening?"); `24:00`, `13pm`,
`7:60am`, `0am`, start == end raise. Real sweep (163 distinct messages):
42 hours, 2 unreadable (`9am -11:59`), matching the 44 measured.
Mutation check found two dead rules (`24/7`: those messages have no
range; re-reading a day range's ends), removed, and two test gaps.
The scratch runner needed a fresh `PYTHONPYCACHEPREFIX` per mutant: a
stale `.pyc` made a same-length `23`->`24` mutant look survived.
- Wired (2026-11-26): `parse_detour` sets `daily_hours`; a `ValueError`
  becomes `hours: <reason>` (decided: the notice turns partial). Pins:
  route 44 #3 (`9am -11:59`) joins `NOT_COMPLETE`; a new `HOURS` pin
  lists the 8 fixture items with hours (103 #0-1, 2 #0, 24 #2-3, 32 #2
  overnight, 61 #0-1).
