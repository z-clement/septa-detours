// Page bootstrap: build the map, load the data, draw it, report status.
//
// Loaded by index.html as a module, after maplibre-gl.js (so the global
// `maplibregl` exists for mapview.js).

import { loadDetours } from "./data.js";
import { summarize } from "./format.js";
import { addDetourLayers, addPopups, collectionBounds, createMap } from "./mapview.js";

/**
 * Show a short status line on the page.
 *
 * @param {string} message
 */
function showStatus(message) {
  // textContent (not innerHTML) so the message can't inject markup.
  document.getElementById("status").textContent = message;
}

/**
 * Show an error message on the page (and in the console).
 *
 * @param {string} message
 */
function showError(message) {
  console.error(message);
  document.getElementById("error").textContent = message;
}

/** Build the map, load the data, draw it, and zoom to it. */
async function main() {
  const map = createMap("map"); // the id of the <div>

  // The style loading and our data download are independent, so start both
  // and wait for both. `map.once("load")` with no callback returns a Promise.
  // Promise.all resolves to an array of results, in the order given; the
  // `[, collection]` skips the first (the load event, which we don't need).
  const [, collection] = await Promise.all([
    map.once("load"),
    loadDetours(),
  ]);

  addDetourLayers(map, collection);
  addPopups(map);
  showStatus(summarize(collection));

  // No bounds means no detours: a true state, not an error. The map stays
  // on Philadelphia and the status line says so.
  const bounds = collectionBounds(collection);
  if (bounds !== null) {
    map.fitBounds(bounds, { padding: 40, duration: 0 });
  }
}

// An async function returns a Promise; an error thrown inside it becomes a
// rejection, which `.catch` turns into a visible message instead of a
// silent console-only failure.
main().catch((err) => showError(err.message));
