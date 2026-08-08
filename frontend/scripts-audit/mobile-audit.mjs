/* Mobile-layout audit: drives REAL Chrome at a phone viewport (390x844,
   touch, DPR 3) against every route and asserts two properties the
   desktop gates cannot see (LOG entry 56):

   1. No horizontal overflow: scrollWidth must not exceed the viewport.
      Every table already ships inside .table-scroll; anything else that
      pushes the page sideways is a bug.
   2. Effective tap areas: every interactive element must accept a touch
      across ~40px. Measured by PROBING (elementFromPoint at the center
      and four offset points), not by bounding box, so hit areas extended
      via pseudo-elements (.i-btn::after) count — that extension is
      load-bearing here.

   Browser resolution mirrors audit:tips: CHROME_PATH env first,
   otherwise the installed Chrome. */
import puppeteer from "puppeteer-core";
import { pathToFileURL } from "node:url";
import path from "node:path";

const PAGE = pathToFileURL(
  path.resolve(import.meta.dirname, "tip-page.html")).href;
const ROUTES = ["/", "/upcoming", "/scoreboard", "/model", "/markets", "/trends",
                "/backtest", "/how", "/match/m1"];
const VIEW = { width: 390, height: 844, deviceScaleFactor: 3,
               isMobile: true, hasTouch: true };
const PROBE = 14;          // center +/- px; 4 passing probes ~= 43px hit area
const CLICKABLE = "a[href], button, [role=button], .clickable";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const launchOpts = process.env.CHROME_PATH
  ? { executablePath: process.env.CHROME_PATH,
      headless: process.env.CHROME_HEADLESS === "shell" ? "shell" : true,
      args: (process.env.CHROME_ARGS || "").split(/\s+/).filter(Boolean) }
  : { channel: "chrome", headless: true };
let browser;
try {
  browser = await puppeteer.launch({ ...launchOpts, defaultViewport: VIEW });
} catch (e) {
  console.error("MOBILE AUDIT: could not launch Chrome.", e.message);
  console.error("Install Google Chrome, or point CHROME_PATH at a "
    + "Chrome/Chromium binary.");
  process.exit(1);
}
const page = await browser.newPage();
const failures = [];
let probedTargets = 0;

for (const route of ROUTES) {
  await page.goto(`${PAGE}?r=${encodeURIComponent(route)}#${route}`,
    { waitUntil: "load" });
  await sleep(350);                      // effects + fonts settle

  const over = await page.evaluate(() => {
    const el = document.scrollingElement || document.documentElement;
    return { sw: el.scrollWidth, iw: window.innerWidth };
  });
  if (over.sw > over.iw + 1) {
    failures.push(`${route}: horizontal overflow ${over.sw}px > `
      + `${over.iw}px viewport`);
  }

  const bad = await page.evaluate((sel, probe) => {
    const out = [];
    const els = [...document.querySelectorAll(sel)];
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;    // hidden
      if (Math.min(r.width, r.height) >= 40) { out.push(null); continue; }
      el.scrollIntoView({ block: "center", inline: "nearest" });
      const q = el.getBoundingClientRect();
      const cx = q.left + q.width / 2, cy = q.top + q.height / 2;
      const pts = [[cx, cy], [cx - probe, cy], [cx + probe, cy],
                   [cx, cy - probe], [cx, cy + probe]];
      const ok = pts.every(([x, y]) => {
        if (x < 0 || y < 0 || x >= window.innerWidth
            || y >= window.innerHeight) return true;    // off-screen probe
        const hit = document.elementFromPoint(x, y);
        return hit && (el === hit || el.contains(hit) || hit.contains(el));
      });
      out.push(ok ? null : (el.className || el.tagName).toString()
        .slice(0, 60));
    }
    return { probed: out.length, misses: out.filter(Boolean) };
  }, CLICKABLE, PROBE);
  probedTargets += bad.probed;
  for (const m of bad.misses.slice(0, 4)) {
    failures.push(`${route}: tap target too small / occluded: ${m}`);
  }
  console.error(`OK-scan ${route}  width=${over.sw}/${over.iw}  `
    + `targets=${bad.probed} misses=${bad.misses.length}`);
}

await browser.close();
if (failures.length) {
  console.error("MOBILE AUDIT FAILURES:");
  for (const f of failures) console.error("  " + f);
  process.exit(1);
}
console.error(`MOBILE AUDIT: all ${ROUTES.length} routes fit 390px, `
  + `${probedTargets} tap targets OK`);
