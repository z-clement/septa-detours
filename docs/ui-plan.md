# UI/UX plan: a map readable at a glance (draft, 2026-11-26)

Written from your point of view: "I", "my choice" = you. Status: **draft**,
waiting for your screenshots of the current map before proposing
designs. Nothing here is decided unless it says so.

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

## Screenshots wanted

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
