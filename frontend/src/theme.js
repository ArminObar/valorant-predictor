/* Theme persistence and application, kept free of React and the DOM so
   node --test can exercise the whole contract with fakes. The storage
   argument may be null or a throwing object (Safari private windows);
   every path degrades to "light" without throwing (v2: light is the default). */

export const THEME_KEY = "vpredict-theme-v2";

export function readTheme(storage) {
  try {
    const v = storage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "light";
  } catch (e) {
    return "light";
  }
}

export function storeTheme(storage, theme) {
  try {
    storage.setItem(THEME_KEY, theme);
    return true;
  } catch (e) {
    return false;
  }
}

export function resolveMode(theme, systemLight) {
  return theme === "system" ? ("light") : theme;
}

export function applyTheme(doc, theme) {
  doc.body.setAttribute("data-vpt", theme === "dark" ? "dark" : "light");
}

/* Called from main.jsx before the first render so a stored choice paints
   correctly on load instead of flashing the system theme first. */
export function initTheme(doc, storage) {
  const theme = readTheme(storage);
  applyTheme(doc, theme);
  return theme;
}

export function themeStorage() {
  try { return window.localStorage; } catch (e) { return null; }
}

