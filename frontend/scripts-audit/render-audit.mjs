import { JSDOM } from "jsdom";
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost/", pretendToBeVisual: true });
for (const k of ["window", "document", "HTMLElement", "HTMLMediaElement",
  "HTMLCanvasElement", "Node", "localStorage", "getComputedStyle",
  "requestAnimationFrame", "cancelAnimationFrame"]) {
  try { globalThis[k] = dom.window[k]; } catch { /* getter-only global */ }
}
Object.defineProperty(globalThis, "navigator",
  { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.matchMedia = globalThis.matchMedia = () => ({ matches: false,
  addEventListener() {}, removeEventListener() {}, addListener() {},
  removeListener() {} });
dom.window.HTMLMediaElement.prototype.play = () => Promise.resolve();
dom.window.HTMLMediaElement.prototype.pause = () => {};
dom.window.HTMLCanvasElement.prototype.getContext = () => null;
dom.window.scrollTo = globalThis.scrollTo = () => {};
await import("./render-bundle.mjs");
