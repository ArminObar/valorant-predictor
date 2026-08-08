import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import App from "../src/App.jsx";
import { PAYLOADS as P } from "./payloads.mjs";

const ROUTES = ["/", "/upcoming", "/scoreboard", "/model", "/markets",
                "/trends", "/backtest", "/how", "/match/m1"];
// Payload-driven sections that MUST appear in the rendered text when the
// mock provides their data. A build that compiles but silently drops a
// wired section is exactly the class the v2 crisis taught us about
// (LOG entries 43-58); "zero console errors" is vacuous for it. Checked
// case-insensitively against document.body.textContent.
const MUST_CONTAIN = {
  "/markets": ["unit tracker", "provisional", "RED vs BLU"],
  "/trends": ["Sample Squad", "pistol", "all history",
    "current form", "teams in scope"],
  "/upcoming": ["low history (2/1)"],
};
const errors = [];
const realErr = console.error;
console.error = (...a) => { errors.push(a.join(" ")); };

globalThis.fetch = (url) => {
  const key = Object.keys(P).find((k) => String(url).startsWith(k));
  return Promise.resolve({ ok: !!key, status: key ? 200 : 404,
    json: () => Promise.resolve(P[key] ?? {}) });
};

let fails = 0;
for (const r of ROUTES) {
  errors.length = 0;
  document.body.innerHTML = '<div id="root"></div>';
  try {
    const root = createRoot(document.getElementById("root"));
    await act(async () => {
      root.render(<MemoryRouter initialEntries={[r]}><App /></MemoryRouter>);
    });
    await act(async () => { await new Promise((res) => setTimeout(res, 30)); });
    const tabs = document.querySelectorAll(".tab").length;
    const text = document.body.textContent.toLowerCase();
    const missing = (MUST_CONTAIN[r] || [])
      .filter((s) => !text.includes(s.toLowerCase()));
    const bad = errors.filter((e) => !/not wrapped in act/.test(e));
    if (bad.length) { fails += 1; realErr(`FAIL ${r}: ${bad[0].slice(0, 160)}`); }
    else if (missing.length) {
      fails += 1;
      realErr(`FAIL ${r}: rendered without required content: ` +
        missing.map((s) => JSON.stringify(s)).join(", "));
    }
    else realErr(`OK   ${r}  tabs=${tabs} text=${document.body.textContent.length}ch`);
    root.unmount();
  } catch (e) { fails += 1; realErr(`THROW ${r}: ${String(e).slice(0, 160)}`); }
}
realErr(fails === 0 ? "RENDER AUDIT: all routes clean" : `RENDER AUDIT: ${fails} failing`);
process.exit(fails === 0 ? 0 : 1);
