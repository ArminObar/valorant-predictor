/* Tip-geometry audit: drives REAL Chrome against the built page and
   asserts every info tooltip anchors to its trigger, paints on top, and
   stays on screen. Exists because the jsdom render audit has no layout:
   it passed twice while every pop was displaced by its ancestor's origin
   (LOG entries 48 and 51). Browser resolution: CHROME_PATH env first,
   otherwise the installed Chrome (puppeteer "chrome" channel). */
import puppeteer from "puppeteer-core";
import { pathToFileURL } from "node:url";
import path from "node:path";

const PAGE = pathToFileURL(
  path.resolve(import.meta.dirname, "tip-page.html")).href;
// route -> exact expected icon count; drift in either direction fails.
const EXPECT = { "/upcoming": 1, "/scoreboard": 3, "/model": 2,
                 "/markets": 1, "/backtest": 1 };
const TOL = 3; // px; placement is exact, tolerance is for rounding

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const launchOpts = process.env.CHROME_PATH
  ? { executablePath: process.env.CHROME_PATH,
      headless: process.env.CHROME_HEADLESS === "shell" ? "shell" : true,
      args: (process.env.CHROME_ARGS || "").split(/\s+/).filter(Boolean) }
  : { channel: "chrome", headless: true };
let browser;
try {
  browser = await puppeteer.launch({
    ...launchOpts, defaultViewport: { width: 1440, height: 900 } });
} catch (e) {
  console.error("TIP AUDIT: could not launch Chrome.", e.message);
  console.error("Install Google Chrome, or point CHROME_PATH at a "
    + "Chrome/Chromium binary.");
  process.exit(1);
}
const page = await browser.newPage();
const failures = [];
let probed = 0;
for (const [route, expected] of Object.entries(EXPECT)) {
  await page.goto(`${PAGE}?r=${encodeURIComponent(route)}#${route}`,
    { waitUntil: "load" });
  await page.waitForSelector(".i-btn", { timeout: 4000 })
    .catch(() => {});
  await sleep(700); // entry animations finished and released
  const n = await page.$$eval(".i-btn", (els) => els.length)
    .catch(() => 0);
  if (n !== expected) {
    failures.push(`${route}: expected ${expected} info icons, found ${n}`);
    continue;
  }
  for (let i = 0; i < n; i++) {
    const handles = await page.$$(".i-btn");
    await handles[i].hover();
    await sleep(200);
    const m = await page.evaluate((idx) => {
      const btn = document.querySelectorAll(".i-btn")[idx];
      const b = btn.getBoundingClientRect();
      const pop = document.querySelector(".infotip-pop");
      if (!pop) return { pop: false };
      const p = pop.getBoundingClientRect();
      const cs = getComputedStyle(pop);
      const cx = Math.round(p.left + p.width / 2);
      const cy = Math.round(Math.min(p.top + 12, innerHeight - 2));
      const topEl = document.elementFromPoint(cx, cy);
      return { pop: true, position: cs.position,
        dTop: p.top - (b.bottom + 6),
        dCx: (p.left + p.width / 2) - (b.left + b.width / 2),
        offscreen: p.top >= innerHeight || p.bottom <= 0
          || p.right <= 0 || p.left >= innerWidth,
        covered: !(pop === topEl || pop.contains(topEl)) };
    }, i);
    probed += 1;
    const id = `${route} icon ${i}`;
    if (!m.pop) failures.push(`${id}: no pop rendered on hover`);
    else {
      if (m.position !== "fixed")
        failures.push(`${id}: position ${m.position}, expected fixed`);
      if (Math.abs(m.dTop) > TOL || Math.abs(m.dCx) > TOL)
        failures.push(`${id}: displaced dTop=${m.dTop.toFixed(1)} `
          + `dCx=${m.dCx.toFixed(1)} (tolerance ${TOL})`);
      if (m.covered) failures.push(`${id}: pop painted under another element`);
      if (m.offscreen) failures.push(`${id}: pop off screen`);
    }
    await page.mouse.move(4, 4);
    await sleep(120);
  }
}
await browser.close();
if (failures.length) {
  console.error(`TIP AUDIT: ${failures.length} failure(s):`);
  for (const f of failures) console.error("  FAIL " + f);
  process.exit(1);
}
console.log(`TIP AUDIT: all ${probed} pops anchored, on top, on screen`);
