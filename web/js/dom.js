// Small DOM helpers shared by the sidebar and the map's chooser.
//
// Text always goes in through `textContent`, never `innerHTML`, so names
// from the data can't inject markup.

/**
 * A new element with an optional class and text.
 *
 * @param {string} tag
 * @param {string} [className]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
export function element(tag, className, text) {
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
export function routeBadge(route) {
  const badge = element("span", "badge", route.short_name);
  if (route.color !== null) {
    badge.style.backgroundColor = route.color;
  }
  if (route.text_color !== null) {
    badge.style.color = route.text_color;
  }
  return badge;
}
