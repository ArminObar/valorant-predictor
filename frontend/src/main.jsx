import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { initTheme } from "./theme.js";
import "./index.css";

/* Apply the stored theme before anything renders, so a saved "light"
   choice on a dark-system machine does not flash dark on every load.
   localStorage access itself can throw in locked-down contexts. */
let themeStorage = null;
try { themeStorage = window.localStorage; } catch (e) { themeStorage = null; }
initTheme(document, themeStorage);

createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
);
