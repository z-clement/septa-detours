# Alert fixtures

Real route entries copied from SEPTA alerts API snapshots (`data/raw/alerts/`).

## Rules

- One file = one route entry from the API list, copied with `jq`. Decoded
  values are identical to the snapshot; only JSON formatting differs
  (whitespace, and the API's `\/` escapes become `/`). The full `detour`
  list is kept; tests pick items by index.
- Name: `<snapshot stamp>__<api route_id>.json`. The stamp is the source
  snapshot's file name without `.json`. API `route_id` is unique within a
  snapshot, so names cannot collide.
- Never edit a fixture to make a test pass. If a fixture seems wrong,
  that is a finding about the data or the parser.

Copy command (from the repo root):

```bash
STAMP=2026-11-25T025344Z ROUTE=bus_route_21
jq --arg r "$ROUTE" '.[] | select(.route_id == $r)' \
  "data/raw/alerts/$STAMP.json" > "tests/fixtures/alerts/${STAMP}__${ROUTE}.json"
```

## Index

One row per detour item worth testing (`#` = index in the `detour` list;
`-` = the route entry itself). "Expected" is a guess written before the
parser exists; parse tests are built from it. LS/LE = `location_start` /
`location_end`. One table per source snapshot.

### Snapshot `2026-11-25T025344Z`

| Route | # | What makes it ugly | Expected |
| ----- | - | ------------------ | -------- |
| `bus_route_2` | 0 | Recurring "7am - 4pm Mon thru Fri" window inside a multi-week span; API start is 6:30 AM, not 7am; LE has a double space | SB; start/end from API fields; recurrence not modelled -> issue |
| `bus_route_2` | 2 | "3pn" typo; comma inside the date phrase ("2am on, 11/26/26") | SB; times from API fields, not message |
| `bus_route_2` | 3 | LE describes the closed area, not an endpoint ("JFK/17th to 30th & Market 23rd to 19th"); "S Penn Sq,L - JFK Blvd"; "Right on, 16th St" split by a comma; LS double space | NB; LE kept as cleaned text |
| `bus_route_2` | 4 | "Reg Rte" spelling | complete, NB |
| `rr_route_mfo` | - | Owl *bus* (route `MFO`) with an `rr_` id and mode "Market/ Frankford" | match must not treat it as rail |
| `rr_route_mfo` | 0 | "W/B"; every turn ends in a doubled comma | WB |
| `rr_route_mfo` | 1 | "Schuykill" typo in LS; message ends with trailing spaces | EB |
| `rr_route_mfo` | 2, 3 | Stop closure, not a reroute; "until 12/3126" (date typo) | direction EB / WB; end from API; stop-closure kind (open question) |
| `bus_route_64` | - | `advisory` holds ~650 chars of HTML | ignored by detour parsing |
| `bus_route_64` | 1 | Blank LS *and* LE; two stops in one message ("4th & Washington,, Moyamensing &, Washington") | unknown (no LS) |
| `bus_route_64` | 2 | Blank LS and LE; single stop in message | unknown (no LS) |
| `bus_route_64` | 3, 4 | "Eastbound" / "Westbound" spelled out, at the end; "Until 23:59" (24-hour); same text also on routes 12 and 79 | EB / WB |
| `bus_route_64` | 5 | Clean reroute with no time text in the message at all | complete, WB |
| `bus_route_6` | 0 | Canonical discontinued stop: blank LE, no direction, 4-digit year | stop-closure kind; no direction -> partial |
| `bus_route_9` | 0 | Closure in prose, typo "disontiuned"; LS is the *replacement* boarding spot and LE the closed stop | NB; LS/LE meaning differs from reroutes |
| `bus_route_7` | 0 | Dash shorthand "L-Fairmount R--23rd L-, Spring Garden" (double dash, turn split across a comma); "3pm - 2am 11/25/26, - 11/26/26"; reason double space | SB |
| `bus_route_7` | 1 | LS "22nd  &  Chestnut" (double spaces on both sides) | NB; LS inner spaces collapsed? (decide) |
| `bus_route_31` | 2 | Blank LE; doubled commas; dash date "7-1-27"; schedule repeated *after* "Reg Rt" ("Reg Rt 24/7 11/16/26-, 07/01/27") | EB |
| `bus_route_31` | 3 | No "Reg Rt": ends "Take Recovery On Broad, & Walnut St" (bus short-turns instead of rejoining) | EB |
| `bus_route_24` | 0 | "Gloria Dei Tower/Manor, Trips Only" (affects some trips only); second direction word ("Recover NB On"); LE "Gloria Dei Towers & Maner Discontinued" (typo + status in a location) | NB |
| `bus_route_24` | 1 | No direction at all ("Via Huntingdon Pke") | direction None -> partial |
| `bus_route_24` | 2 | "7am -330pm" (no colon in 3:30) | NB |
| `bus_route_49` | 0, 1 | Same closed stop posted twice with different wording | two notices; both SB |
| `bus_route_49` | 2 | "SB Only" closure; LS == LE; API end "12:59 AM" | SB |
| `bus_route_49` | 3 | Imperative "Discontinue the transit stop, NB on Convention Ave" | NB |
| `bus_route_49` | 5 | "Pennsylvania,Rg Rt" ("Rg Rt", no space after comma); "Left on Vine,," | NB |
| `bus_route_61` | 0, 1 | LS "Ridge Ave & Ridge Ave"; "Stay on Ridge Ave" (no turns); #1 message says 5:30pm, API end says 5:00 PM | SB / NB |
| `rr_route_bso` | - | Owl bus with an `rr_` id, mode "Broad Street Line" | match must not treat it as rail |
| `rr_route_bso` | 0, 1 | Stop *relocation* ("Clothespin stop"), neither reroute nor closure; direction after the time ("Until 12/31/26 11:59pm SB,"); "15th & MArket"; broken parens "(, Clothespin Side )" | SB / NB; kind unclear |
| `bus_route_32` | 0 | Truncated ending "Hunting Park Ave,Reg R" | NB |
| `bus_route_32` | 2 | "Monday thru Wednesday, 7:00PM to 5:00AM": overnight recurring window, no dates in message; "Ben Franklinn Pkwy" | NB; recurrence -> issue |
| `bus_route_44` | 0 | Closure with direction *before* the location ("24/7 EB 5th St & Market St") | EB |
| `bus_route_44` | 3 | Message end date "until, 11/23/26" is earlier than the API end (11/24 11:59 PM); "9am -11:59"; "38th Parallel Pl" (a street name starting with a number) | EB; API times win; mismatch -> issue? (decide) |
| `bus_route_103` | 0, 1 | Blank LE; time range split by a comma ("7:40am -, 6:00 pm"); "Regular Route" spelled out; no end date in message | NB / SB |
| `bus_route_68` | 0, 1 | Identical postings, start one minute apart (`source_key` differs); PNC detour labelled EB here but SB/NB on routes 108/115 | two notices, both EB |
| `bus_route_68` | 2 | "Express Trips Only" (affects some trips only) | NB |
| `bus_route_55` | 0 | Baseline: single clean reroute; only quirks are the dash date "12-31-2026" and a trailing space in `reason` | complete, SB |
| `trolley_route_15` | - | No detours; a trolley whose `mode` is "Bus" | zero notices |
| `APP` | - | System entry ("Mobile APP"), not a route; no detours | zero notices, no error |

### Snapshot `2026-11-25T121123Z`

About 9 hours after the first. Most new detours are Thanksgiving Day
parade reroutes (11/26), posted ~14 hours before they start.

| Route | # | What makes it ugly | Expected |
| ----- | - | ------------------ | -------- |
| `bus_route_31` | 2 | Identical to `bus_route_31` #2 in the earlier snapshot; items 0-4 keep their indices (new items are appended) | same `source_key` as the earlier copy |
| `bus_route_31` | 3, 5 | Parade set-up then parade day: #3 ends 11/26 2:00 AM exactly when #5 starts; both short-turn ("Take recovery at Broad &, Walnut", comma inside the intersection) | two notices, both EB |
| `bus_route_31` | 4, 6 | #6 LS is `"Broad &"` (cross street missing); LE "JFK btwn 20th & 15th/ Art Museum 16th" is an area, not an endpoint | WB; LS kept as `"Broad &"` (incomplete, but not blank) |
| `bus_route_124` | 0, 1 | Date split by a comma ("2am on, 11/26/26"); LS "30th & Chestnut Sts" vs "30th & Chestnut" in #3 (same place, different spelling) | EB / WB |
| `bus_route_124` | 2, 3 | Doubled-dash date "11-26--26" (pasted onto 7 routes); "S PEnn Sq" | WB / EB; times from API fields |
