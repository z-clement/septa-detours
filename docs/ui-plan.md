# UI/UX plan: a map readable at a glance (draft, 2026-11-26)

Written from your point of view: "I", "my choice" = you. Status:
directions A, B, C, E **decided** (2026-11-26); D, F, G proposed, to
confirm before building them. Order of work at the end.

## Goal (decided 2026-11-26)

- **Audience: riders.** Someone checking whether their bus is detoured,
  and where to catch it instead.
- **The 3-second glance (overview):** both *which* routes are detoured
  now and *where* detours are, equally: a map of where, plus an obvious
  list of which.
- **Devices: phone and desktop equally.** Check every decision on both
  (sidebar at >= 700 px, bottom sheet below).

## What the page shows today

Overview, bottom to top: Positron basemap; the whole network in grey;
every detoured route **whole** in its GTFS color; the faded skipped
stretches; dashed detour paths; start dots styled by timing (in effect:
solid route color; upcoming: hollow; ended: grey); a legend (5 rows).
Sidebar: status line, search, mode chips, "Detoured now", every route by
mode with timing counts, "Not on the map".

Focused route: everything else dimmed, every shape of the route, its
dots, small end dots (rejoins), and a panel of cards grouped by timing
(headline, dates, reason, "Back on route ...", raw message).

## Facts measured (snapshot `145719Z`)

- 48 of 181 routes have detours; all 48 are buses.
- **Route color doesn't tell routes apart:** 37 of the 48 detoured
  routes are SEPTA's bus color `#1A1818` (near black), 9 are red
  `#EF3340`, 1 orange, 1 blue. Red also clashes with any "detoured =
  red" idea.
- **"In effect" can mislead riders:** 28 of 101 matched detours run
  only at certain hours ("7am - 4pm Mon thru Fri"); the page calls a
  detour "in effect" for its whole date range (recurring windows aren't
  parsed: `docs/backlog.md`).
- 80 of 104 detours are placed (have a start dot); 36 have a drawn
  path, 38 a faded stretch, 48 a rejoin.
- Timing differs between layers: dots, fades and paths use the
  export-time timing; cards and rejoin dots use the page's clock.

## Problems seen so far (from the code and data; screenshots will add)

1. **A whole route lights up for one short detour.** A 300 m detour on
   a 20 km route draws the full 20 km in color; at a glance the route
   looks detoured everywhere, and the detour's actual place is a small
   mark inside it.
2. **Color carries little.** Most detoured routes are the same near
   black, so the overview can't show *which* route is which without
   labels or a tap.
3. **Hours aren't shown.** A rider at 8 pm sees a "7am - 4pm" detour as
   in effect (problem for the audience we chose).
4. **Many marks, many meanings.** Five legend entries, two dot kinds,
   dashed + faded + solid lines, two offset directions; plus ended and
   upcoming dots on the overview.
5. **Cards lead with location text and the raw message.** A rider wants
   "where do I catch it" (which stops are skipped, where to wait
   instead); stop closures and stops aren't modelled yet (tier A step 4).
6. **Unplaced detours** (24 of 104) exist only in lists.
7. **Timing mismatch** between layers (above).

## By eye (your screenshots, 2026-11-26, snapshot `145719Z`)

1. **Overview, region:** a tangle of near-black lines over the whole
   region; the 48 detoured routes, drawn whole, *are* the picture. Start
   dots (small, mostly black with a white ring) vanish among them. The
   list on the left answers "which" well; the map doesn't answer
   "where".
2. **Overview, Center City:** readable here: dashed paths and dots stand
   out, the fade shows (pale pink/blue). But every detoured route is a
   double line (two directions offset), crossing others; three dot
   styles (solid, hollow = upcoming, grey = ended) mean three things;
   the legend lists "Back on route here", which the overview never
   draws.
3. **Route 19 focused:** route solid, paths dashed, clear. But the
   start dot (black, white ring) and the rejoin dot (black, dark ring)
   look the same at this size; NB/SB twin detours sit on top of each
   other; the fade on a black double line barely shows.
4. **Route 124 focused:** the camera fits the *whole route* (King of
   Prussia to Center City), so its two detours are specks at either
   end; selecting a card highlights it but the map doesn't go there.
5. **Phone overview:** the same tangle in a small map; the legend
   covers about a fifth of it.
6. **Phone, route 31 focused:** the detours are a few pixels in the
   middle; the legend covers the route's west end.

## Design directions

Each answers one or more problems above. **Decided** (2026-11-26, all
the recommended options): **A1, B1, C1, E1**. D, F, G: proposed.

A. **Overview: detours, not routes** (problems 1, 2, by-eye 1, 2, 5).
   - A1 **(recommended)** Routes recede (detoured routes thin and grey,
     like the network); each detour in effect is drawn in **one accent
     color** (a color no SEPTA route uses): its path, the fade, its
     start marker. Route identity comes from a label on the marker
     and from the list.
   - A2 Keep route colors; only the detour's stretch and path in
     color, the rest of each detoured route grey.
   - A3 Keep today's look; only thin the lines and enlarge the dots.
B. **Zoomed out: markers, not lines** (by-eye 1, 5).
   - B1 **(recommended)** Below ~zoom 13 the map shows one marker per
     detour (a pin with the route number); lines appear from zoom 13.
     Answers "where" *and* "which" on the map itself.
   - B2 Lines at every zoom (today), markers just bigger.
C. **Focusing frames the detours** (by-eye 4, 6).
   - C1 **(recommended)** Focusing a route fits its detours in effect
     (paths, stretches, dots), not the whole route; selecting a card
     zooms to that detour. "Whole route" stays one tap away.
   - C2 Keep fitting the whole route; selecting a card zooms in.
D. **One line per route, not two** (by-eye 2, 3).
   - D1 **(recommended)** No direction offset on the overview (one
     centreline per route). Focused: both directions drawn, but a
     selected detour's direction emphasized and the other dimmed.
   - D2 Keep the offsets everywhere (today).
E. **Time, as a rider means it** (problem 3, 7, by-eye 2).
   - E1 **(recommended)** The map shows only detours in effect now
     (upcoming and ended stay in the panel), all layers timed by the
     page's clock; then parse daily hours ("7am - 4pm Mon thru Fri")
     so "in effect" means *running now*, and cards say the hours.
   - E2 Map timing only (no hours parsing yet).
F. **Cards for riders** (problem 5, by-eye 3): the detour as steps
   ("Left on Rhawn St, Right on Verree Rd, ..."), hours, "Back on route
   at ...", the raw message collapsed; start and rejoin as distinct
   markers (e.g. lettered **A** / **B**, matching the card). Later:
   closed stops and where to wait (tier A step 4).
G. **Legend** (by-eye 2, 5, 6): only rows for what's drawn; on phones a
   small "Key" button that opens it.

## Screenshots wanted (done)

Desktop, a normal window:
1. The overview at the default view.
2. The overview zoomed into Center City (zoom ~14).
3. Route 19 focused (`#route=bus-19`): 4 detours, all with a path,
   stretch and rejoin.
4. Route 124 focused with a detour selected (click a card).

Phone (DevTools device mode, ~390 x 844):
5. The overview, sheet at half.
6. Route 31 focused (`#route=bus-31`), sheet at half.

## Next

1. Your screenshots -> by-eye findings added above.
2. Design options per problem (with sketches), each a decision for
   you; recommendations marked.
3. An order of work in small, checkable steps, like `web-plan.md`'s.

## Order of work (proposed)

Small steps, each tested (pure JS where possible), committed, then
checked by eye with your screenshots. Rough sizes in brackets.

- **U1. Time (E1, first half)** (done 2026-11-26: contract 6, features
  carry start/end; not yet checked by eye) [small, JS]: every layer timed by the
  page's clock (`detourTiming` per `source_key`, applied as a filter);
  the map shows only detours in effect; upcoming and ended stay in the
  panel.
- **U2. Accent overview (A1)** (done 2026-11-26: magenta `#D500F9`; not
  yet checked by eye) [medium, JS + CSS]: detoured routes thin
  grey like the network; paths, fades and start markers in one accent
  color (checked against every SEPTA route color); legend updated.
- **U3. Route-number markers (B1)** (done 2026-11-26; not yet checked by
  eye: threshold, crowding in Center City) [medium, JS]: below ~zoom 13 one
  labelled marker per detour (a MapLibre symbol layer: the basemap's
  fonts); lines from zoom 13. Check the threshold by eye.
- **U4. Focus frames detours (C1)** (done 2026-11-26; focused, detour
  layers at every zoom, no markers; not yet checked by eye)
  [small-medium, JS]: fit the focused
  route's detours in effect; a selected card zooms to its detour; a
  "Whole route" control.
- **U5. Directions (D)** (done 2026-11-26: your choice, arrows on the
  focused route from zoom 13, nothing faded; the overview keeps two
  lines; not yet checked by eye) [small-medium, JS]. Asked for (yours,
  2026-11-26, after U3): on a focused route the two directions are hard
  to tell apart (route 47 NB vs SB): show direction (arrows along the
  line?) and/or fade the direction that isn't the focused detour's.
  Confirm the exact form when we get here.
- **U5b. One line per direction** (done 2026-11-26, contract 9; not yet
  checked by eye) (yours, 2026-11-26, seen on route 79
  zoomed in: four lines on Snyder, two per direction) [medium: export
  geometry + contract change]. Cause, measured (`145719Z`): a direction
  is drawn once per GTFS shape, and shapes of one direction are
  digitized up to a metre or so apart (route 79 on Snyder: 5 shapes
  within ~1 m), so they split apart when zoomed in. 141 of 341
  route-directions draw more than one network line; route detail files
  have 2-20 shapes in 212 route-directions. Proposed fix: at export,
  merge each route-direction's shapes into non-overlapping pieces
  (busiest shape first; later shapes keep only their parts more than
  ~10 m from what's kept; tiny leftovers dropped; travel order kept for
  the arrows), for `network.geojson` and the route detail's `shapes`.
- **U6. Legend (G)** (done 2026-11-26: rows for what's drawn, a 'Map
  key' button closed on phones) [small, JS + CSS].
- **U7. Rider cards (F)** (done 2026-11-26: turn-by-turn steps and the
  raw message collapsed; no A/B markers; contract 7) [medium: contract gains the
  steps, schema bump].
- **Color pass (yours, 2026-11-26)** (done: palette A, smaller zoomed-out
  markers) [small]: once the UI is settled,
  one pass over every color (accent, greys, route colors, dots,
  legend), together. Magenta is fine for now.
- **Match follow-up (not UI, seen 2026-11-26 on route 79):** a path can
  start off the route; a lead-in from the route to the start point is
  logged in `geography-plan.md` (tier C follow-ups). Fit it in between
  UI steps.
- **U8. Daily hours (E1, second half)** (done 2026-11-26: `parse/hours.py`,
  `DailyHours`, contract 8, map hides off-hours detours, cards say the
  hours; not yet checked by eye) [large: parse windows from the
  message (`parse/`), model + contract changes (flagged), "running now"
  on the page]. Its own short plan first: the message formats seen,
  measured on the snapshots.

## U8 plan: daily hours (measured 2026-11-26)

All 163 distinct messages in the 4 snapshots, by how they state time:

| kind | messages | example | handled today? |
|---|---|---|---|
| recurring hours + days | 39 | "7am - 4pm, Mon - Fri until 11/30/26" | **no** |
| recurring hours, every day | 5 | "7am - 4pm until 1/1/27" | **no** |
| hours on one date / one range | 27 | "2am - 10pm on 11-26-26" | yes: parse's start/end already are 02:00-22:00 |
| until a time/date | 44 | "Until 2am on Thurs 11/26/26" | yes |
| 24/7 | 24 | "24/7 until 12-26-26" | yes |
| other / none | 24 | stop closures, "Until Further Notice" | yes |

So **44 of 163 (27%) need daily hours**. Forms seen: hours before or
after the days; `Mon - Fri`, `Mon thru Fri`, `Mon - Friday`,
`Weekdays`, `Weekdays only`, `Mon & Tues`, `Mon - Tues`,
`Monday thru Wednesday`; times `7am`, `8:30am`, `-330pm` (no colon),
`7:00PM`, `11:59` (no am/pm); an overnight window ("7:00PM to 5:00AM");
a range split by a comma ("7:40 am -, 6:00 pm"). The API's end time can
disagree with the message ("7am - 6pm" ends 16:00): a known mismatch
(backlog).

Proposed design:
1. `parse/hours.py` (pure): `parse_daily_hours(message)` -> `DailyHours`
   (`days`: weekdays it runs; `start`, `end`: local times; `end` before
   `start` = overnight, counted on the start's day) or `None`.
2. `DetourNotice.daily_hours` (model change, flagged; default `None`).
3. Contract (schema bump): the detour object and detour features carry
   `hours` (`{days, start, end}` or null).
4. Page: `isInEffect` also needs the current local time (SEPTA's zone,
   via `Intl`) inside the hours; cards say the hours ("Weekdays 7am -
   4pm") and whether it's running now.

Decided (2026-11-26): outside its hours a detour is **hidden** on the
map like an upcoming one (its card stays, saying the hours and "not
running now"); a time range parse can't read as daily hours gets a
**parse issue** (the notice becomes partial; parse's pins move, to
review); **U8 before U5b**.

## Render sweep (2026-11-26, Claude, headless Brave; evening, snapshot `145719Z`)

Checked and working: overview markers (grey routes, magenta labelled
markers), zoom >= 13 detail (dashed paths with arrows, skipped bands,
start dots), focus framing (route 19's detours; route 124 with all
detours ended falls back to the whole route), direction arrows, one
line per direction (route 79), hours ("not running now", the off-hours
detour hidden), phone: "Map key" closed, route 31 framed above the
sheet. Findings, none fixed yet:

1. **Crowded markers lose their numbers**: around City Hall and where a
   route's two directions start at one corner (two overlapping
   markers); worst on a phone, where Center City is one clump.
   Options: cluster at low zoom (a count), or one marker per route.
2. **Detoured-route grey vs network grey** are too close to tell apart
   (color pass).
3. **"Detoured now" counts ignore daily hours**: the list uses dates
   only, the map dates and hours, so at night they disagree.
4. **Start dots have no route number** from zoom 13 on: near City Hall
   you can't tell whose dot is whose without clicking.
5. **Phone overview markers clump** (see 1).
6. **Attribution box** spreads over two lines at the bottom of a phone's
   map: MapLibre's compact attribution (an (i) button) would fix it.
7. **"In effect (3)" lists a detour "not running now"** (off-hours): a
   heading that contradicts its card. Options: a "Not running now"
   group, or call the group "Current".

Fixed (2026-11-26, same day): 1 and 5 (one marker per route per place,
your choice; smaller markers zoomed out; different routes can still
overlap on a phone's region view), 2 (palette A, your choice from three
renders), 3 and 7 (contract 10; "Not running now" group, your choice),
4 (route numbers beside start dots), 6 (compact attribution).
