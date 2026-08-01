/* Browser entry for the tip-geometry audit: the real App under a
   HashRouter so one static page can serve every route, with the shared
   canned payloads stubbing fetch. */
import React from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "../src/App.jsx";
import { PAYLOADS as P } from "./payloads.mjs";

window.fetch = (url) => {
  const key = Object.keys(P).find((k) => String(url).startsWith(k));
  return Promise.resolve({ ok: !!key, status: key ? 200 : 404,
    json: () => Promise.resolve(P[key] ?? {}) });
};
createRoot(document.getElementById("root")).render(
  <HashRouter><App /></HashRouter>);
