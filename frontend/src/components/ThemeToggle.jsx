import React, { useState } from "react";
import { applyTheme, readTheme, storeTheme } from "../theme.js";

export function ThemeToggle() {
  const [theme, setTheme] = useState(() => readTheme(themeStorage()));
  useEffect(() => { applyTheme(document, theme); }, [theme]);
  const sysLight = window.matchMedia
    && window.matchMedia("(prefers-color-scheme: light)").matches;
  const mode = resolveMode(theme, sysLight);
  const toggle = () => {
    const next = mode === "dark" ? "light" : "dark";
    storeTheme(themeStorage(), next);
    setTheme(next);
  };
  return (
    <button className="theme-btn" onClick={toggle} title="switch theme">
      <span className={`theme-dot ${mode}`} />{theme === "system" ? "auto" : theme}
    </button>
  );
}

/* Panel title with an "about" toggle that expands the long explanation. */
