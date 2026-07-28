/* Theme persistence and application, kept free of React and the DOM so
   node --test can exercise the whole contract with fakes. The storage
   argument may be null or a throwing object (Safari private windows);
   every path degrades to "system" without throwing. */

export const THEME_KEY = "vpredict-theme";

export function readTheme(storage) {
  try {
    const v = storage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch (e) {
    return "system";
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
  return theme === "system" ? (systemLight ? "light" : "dark") : theme;
}

export function applyTheme(doc, theme) {
  if (theme === "system") doc.body.removeAttribute("data-vpt");
  else doc.body.setAttribute("data-vpt", theme);
}

/* Called from main.jsx before the first render so a stored choice paints
   correctly on load instead of flashing the system theme first. */
export function initTheme(doc, storage) {
  const theme = readTheme(storage);
  applyTheme(doc, theme);
  return theme;
}
