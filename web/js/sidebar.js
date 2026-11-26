// The sidebar's DOM: the route list and the route panel.
//
// Only builds elements; what goes in them comes from the PURE modules
// (routes.js, format.js), which have the tests. Text always goes in through
// `textContent`, never `innerHTML`, so names from the data can't inject markup.

import { detourTiming, groupByTiming } from "./detours.js";
import {
  TIMING_WORDS,
  detourHeadline,
  directionSummary,
  formatTime,
  modeLabel,
  routeLabel,
  timingHeading,
  timingSummary,
  unmatchedSummary,
} from "./format.js";
import { detouredNow, groupByMode, timingCounts } from "./routes.js";

/**
 * A new element with an optional class and text.
 *
 * @param {string} tag
 * @param {string} [className]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className !== undefined) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

/**
 * A route's colored badge with its short name ("21", "L1").
 *
 * Colours missing from the data (`null`) are left to the CSS defaults
 * rather than set here.
 *
 * @param {object} route a routes.json entry
 * @returns {HTMLElement}
 */
function routeBadge(route) {
  const badge = element("span", "badge", route.short_name);
  if (route.color !== null) {
    badge.style.backgroundColor = route.color;
  }
  if (route.text_color !== null) {
    badge.style.color = route.text_color;
  }
  return badge;
}

/**
 * One route's row: badge, long name, detour count by timing.
 *
 * A `<button>` so it's focusable and clickable; `data-key` names the
 * route for the click handler (main.js listens on the whole list).
 *
 * @param {object} route a routes.json entry
 * @param {Date} now
 * @returns {HTMLButtonElement}
 */
function routeRow(route, now) {
  const row = element("button", "route-row");
  row.type = "button"; // not "submit", should it ever sit in a form
  row.dataset.key = route.key;
  if (!route.has_shapes) {
    row.classList.add("no-shapes");
    row.title = "No map lines for this route";
  }

  row.append(
    routeBadge(route),
    element("span", "name", route.long_name ?? ""),
    element("span", "count", timingSummary(timingCounts(route, now))),
  );
  return row;
}

/**
 * A titled list of route rows.
 *
 * @param {string} title
 * @param {object[]} routes routes.json entries, in display order
 * @param {Date} now
 * @returns {HTMLElement}
 */
function routeSection(title, routes, now) {
  const section = element("section", "route-section");
  section.append(element("h2", undefined, title), ...routes.map((route) => routeRow(route, now)));
  return section;
}

/**
 * The "Not on the map" section: detours whose route isn't in GTFS.
 *
 * Each is a `<details>`: one summary line plus its timing word, opening
 * to its times, reason and the raw message (no JS needed to toggle).
 *
 * @param {object[]} detours `status.unmatched`
 * @param {Date} now
 * @returns {HTMLElement}
 */
function unmatchedSection(detours, now) {
  const section = element("section", "route-section");
  section.append(
    element("h2", undefined, "Not on the map"),
    element(
      "p",
      "unmatched-note",
      "Their route isn't in SEPTA's GTFS (often a pre-2025 route name).",
    ),
  );
  for (const detour of detours) {
    const item = element("details", "unmatched");
    const summary = element("summary");
    summary.append(
      element("span", "name", unmatchedSummary(detour)),
      element("span", "count", TIMING_WORDS[detourTiming(detour.start, detour.end, now)]),
    );
    item.append(
      summary,
      element("p", undefined, `${formatTime(detour.start)} to ${formatTime(detour.end)}`),
      element("p", undefined, `Reason: ${detour.reason ?? "(none given)"}`),
      element("p", "message", detour.message),
    );
    section.append(item);
  }
  return section;
}

/**
 * Draw the route list into `container`, replacing what was there.
 *
 * "Detoured now" first (left out when no detour is active), then every
 * route grouped by mode, groups in `modeOrder`. A route in "Detoured now"
 * is also in its group. Rebuilt whole on every call: 181 rows is cheap,
 * and it avoids patching. Draws whatever routes it's given, in their
 * order: filtering and ranking are the caller's. No routes shows
 * `emptyText` instead. Unmatched detours, when any are given, come last
 * in "Not on the map" (the caller passes none while filtering).
 *
 * @param {HTMLElement} container
 * @param {object} view
 * @param {object[]} view.routes routes.json entries to show, in order
 * @param {Date} view.now
 * @param {string[]} view.modeOrder the catalog's mode order
 * @param {string} view.emptyText shown when `routes` is empty
 * @param {object[]} view.unmatched `status.unmatched` detours to list
 */
export function renderRouteList(container, { routes, now, modeOrder, emptyText, unmatched }) {
  if (routes.length === 0) {
    container.replaceChildren(element("p", "route-list-empty", emptyText));
    return;
  }
  const sections = [];
  const active = detouredNow(routes, now);
  if (active.length > 0) {
    sections.push(routeSection("Detoured now", active.map((row) => row.route), now));
  }
  for (const group of groupByMode(routes, modeOrder)) {
    sections.push(routeSection(modeLabel(group.mode), group.routes, now));
  }
  if (unmatched.length > 0) {
    sections.push(unmatchedSection(unmatched, now));
  }
  container.replaceChildren(...sections);
}

/**
 * Build the mode chips once; returns the function that updates them.
 *
 * One toggle `<button>` per mode, in `modeOrder`. Built once and then
 * only updated (not rebuilt) so a chip toggled from the keyboard keeps
 * its focus. `aria-pressed` says whether a chip is on; an "unavailable"
 * chip (the search has no routes of that mode) is greyed but still
 * toggles.
 *
 * @param {HTMLElement} container
 * @param {string[]} modeOrder
 * @param {(mode: string) => void} onToggle called with the clicked chip's mode
 * @returns {(on: Set<string>, available: Set<string>) => void}
 */
export function createModeChips(container, modeOrder, onToggle) {
  const chips = modeOrder.map((mode) => {
    const chip = element("button", "chip", modeLabel(mode));
    chip.type = "button";
    chip.addEventListener("click", () => onToggle(mode));
    return { mode, chip };
  });
  container.replaceChildren(...chips.map(({ chip }) => chip));
  return (on, available) => {
    for (const { mode, chip } of chips) {
      chip.setAttribute("aria-pressed", String(on.has(mode)));
      chip.classList.toggle("unavailable", !available.has(mode));
    }
  };
}

/**
 * One detour's card: where, when, why, the raw message.
 *
 * An unplaced detour (no `start_point`) gets a muted note instead of
 * being hidden (decided: it stays in its timing group). Parse issues are
 * debugging text, so they sit in a closed `<details>`.
 *
 * @param {object} detour a detour object
 * @param {object[]} directions the route detail's `directions`
 * @param {boolean} selected
 * @returns {HTMLElement}
 */
function detourCard(detour, directions, selected) {
  const card = element("article", "detour-card");
  card.dataset.sourceKey = detour.source_key;
  card.classList.toggle("selected", selected);
  card.append(
    element("h3", undefined, detourHeadline(detour, directions)),
    element("p", "when", `${formatTime(detour.start)} to ${formatTime(detour.end)}`),
    element("p", undefined, `Reason: ${detour.reason ?? "(none given)"}`),
  );
  if (detour.start_point === null) {
    card.append(element("p", "unplaced", "Location not found on the map"));
  }
  card.append(element("p", "message", detour.message));
  if (detour.issues.length > 0) {
    const notes = element("details", "issues");
    const list = element("ul");
    list.append(...detour.issues.map((issue) => element("li", undefined, issue)));
    notes.append(element("summary", undefined, `Parser notes (${detour.issues.length})`), list);
    card.append(notes);
  }
  return card;
}

/**
 * The panel's header: Back button, badge and names, directions.
 *
 * @param {object} route a routes.json entry
 * @param {object | null} detail its route detail, once loaded
 * @param {() => void} onBack
 * @returns {HTMLElement}
 */
function panelHeader(route, detail, onBack) {
  const header = element("header", "panel-header");
  const back = element("button", "back", "\u2190 All routes");
  back.type = "button";
  back.addEventListener("click", onBack);
  const title = element("h2");
  title.append(routeBadge(route), element("span", "name", route.long_name ?? ""));
  title.title = routeLabel(route);
  header.append(back, title);
  if (detail !== null && detail.directions.length > 0) {
    const directions = element("ul", "directions");
    directions.append(
      ...detail.directions.map((d) => element("li", undefined, directionSummary(d))),
    );
    header.append(directions);
  }
  if (!route.has_shapes) {
    header.append(element("p", "panel-note", "No map lines for this route."));
  }
  return header;
}

/**
 * Draw one route's panel into `container`, replacing what was there.
 *
 * Its detours grouped by timing (in effect, upcoming, dates unknown,
 * ended); "Ended" is a closed `<details>` (D6). Re-rendering the same
 * route (the per-minute refresh) keeps "Ended" open if it was. Before the
 * detail file arrives, `detail` is null and the panel says it's loading;
 * a failed load shows `error` instead.
 *
 * @param {HTMLElement} container
 * @param {object} view
 * @param {object} view.route the focused route's routes.json entry
 * @param {object | null} view.detail its routes/<key>.json, or null while loading
 * @param {string | null} view.error why the detail didn't load
 * @param {Date} view.now
 * @param {string | null} view.selectedDetour a detour's `source_key`
 * @param {() => void} view.onBack
 */
export function renderRoutePanel(container, { route, detail, error, now, selectedDetour, onBack }) {
  const endedWasOpen =
    container.dataset.key === route.key &&
    container.querySelector("details.timing-ended")?.open === true;
  container.dataset.key = route.key;

  const body = element("div", "panel-body");
  if (error !== null) {
    body.append(element("p", "panel-note error", error));
  } else if (detail === null) {
    body.append(element("p", "panel-note", "Loading\u2026"));
  } else if (detail.detours.length === 0) {
    body.append(element("p", "panel-note", "No detours on this route."));
  } else {
    for (const { timing, detours } of groupByTiming(detail.detours, now)) {
      const ended = timing === "ended";
      const group = element(ended ? "details" : "section", `timing-group timing-${timing}`);
      const heading = timingHeading(timing, detours.length);
      group.append(
        ended ? element("summary", undefined, heading) : element("h3", "group-heading", heading),
        ...detours.map((d) =>
          detourCard(d, detail.directions, d.source_key === selectedDetour),
        ),
      );
      if (ended) {
        group.open = endedWasOpen;
      }
      body.append(group);
    }
  }
  container.replaceChildren(panelHeader(route, detail, onBack), body);
}
