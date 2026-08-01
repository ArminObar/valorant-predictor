import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import App from "../src/App.jsx";
import { PAYLOADS as P } from "./payloads.mjs";

const ROUTES = ["/", "/upcoming", "/scoreboard", "/model", "/markets",
                "/backtest", "/how", "/match/m1"];
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
    const bad = errors.filter((e) => !/not wrapped in act/.test(e));
    if (bad.length) { fails += 1; realErr(`FAIL ${r}: ${bad[0].slice(0, 160)}`); }
    else realErr(`OK   ${r}  tabs=${tabs} text=${document.body.textContent.length}ch`);
    root.unmount();
  } catch (e) { fails += 1; realErr(`THROW ${r}: ${String(e).slice(0, 160)}`); }
}
realErr(fails === 0 ? "RENDER AUDIT: all routes clean" : `RENDER AUDIT: ${fails} failing`);
process.exit(fails === 0 ? 0 : 1);
