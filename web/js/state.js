// The page's state: one object, changed only through the actions here,
// which then tell subscribers what changed. Plus the URL hash that
// mirrors the focused route and selected detour.
//
// PURE: no DOM, no `maplibregl`, no fetch (main.js reads and writes
// `location.hash`; this module only parses and formats it).

/**
 * @typedef {object} State
 * @property {string | null} focus the focused route's key, or null (overview)
 * @property {string | null} selectedDetour a detour's `source_key`; only
 *   with a focused route
 * @property {string} search the search box's text
 * @property {ReadonlySet<string>} modes the modes switched on
 * @property {Date} now the time detour timing is computed at
 */

/**
 * Create the page's state store.
 *
 * Each snapshot from `get()` is frozen and never changed afterwards (an
 * action builds a new one; `modes` is a new Set each time), so a
 * subscriber can keep the previous snapshot to compare. Listeners get the
 * new state and the set of keys that changed; an action that changes
 * nothing notifies no one.
 *
 * @param {{modes: Iterable<string>, now: Date}} initial every mode starts on;
 *   no route focused, blank search
 * @returns {{
 *   get: () => State,
 *   subscribe: (listener: (state: State, changed: Set<string>) => void) => () => void,
 *   focus: (key: string | null, detour?: string | null) => void,
 *   setSearch: (text: string) => void,
 *   toggleMode: (mode: string) => void,
 *   setNow: (now: Date) => void,
 * }}
 */
export function createState({ modes, now }) {
  let state = Object.freeze({
    focus: null,
    selectedDetour: null,
    search: "",
    modes: new Set(modes),
    now,
  });
  const listeners = new Set();

  /** Apply `changes`, then notify with the keys whose values differ. */
  const update = (changes) => {
    const changed = new Set(
      Object.keys(changes).filter((key) => !Object.is(changes[key], state[key])),
    );
    if (changed.size === 0) {
      return;
    }
    state = Object.freeze({ ...state, ...changes });
    for (const listener of listeners) {
      listener(state, changed);
    }
  };

  return {
    get: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    // Focus a route (null: back to the overview), optionally selecting one
    // of its detours. No route means no detour: a detour is only ever
    // selected on its focused route.
    focus(key, detour = null) {
      update({ focus: key, selectedDetour: key === null ? null : detour });
    },
    setSearch(text) {
      update({ search: text });
    },
    toggleMode(mode) {
      const modes = new Set(state.modes);
      if (modes.has(mode)) {
        modes.delete(mode);
      } else {
        modes.add(mode);
      }
      update({ modes });
    },
    // Compared by time, not identity: a new Date for the same instant is
    // no change.
    setNow(date) {
      if (date.getTime() !== state.now.getTime()) {
        update({ now: date });
      }
    },
  };
}

/**
 * Read the focused route and selected detour from a URL hash.
 *
 * `"#route=bus-21&detour=5d0d22dfe7d86935"`. Anything missing or empty is
 * null, and a detour without a route is ignored (it can't be selected on
 * the overview). Whether the route exists is the caller's to check.
 *
 * @param {string} hash `location.hash`, with or without the leading "#"
 * @returns {{focus: string | null, selectedDetour: string | null}}
 */
export function parseHash(hash) {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  // `|| null`: get() gives null when absent and "" for "route=".
  const focus = params.get("route") || null;
  const selectedDetour = focus === null ? null : params.get("detour") || null;
  return { focus, selectedDetour };
}

/**
 * The URL hash for a focused route and selected detour; "" on the overview.
 *
 * The inverse of `parseHash`, values URL-encoded.
 *
 * @param {{focus: string | null, selectedDetour: string | null}} state
 * @returns {string} e.g. "#route=bus-21&detour=5d0d22dfe7d86935", or ""
 */
export function formatHash({ focus, selectedDetour }) {
  if (focus === null) {
    return "";
  }
  const params = new URLSearchParams({ route: focus });
  if (selectedDetour !== null) {
    params.set("detour", selectedDetour);
  }
  return `#${params}`;
}
