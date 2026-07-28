import test from "node:test";
import assert from "node:assert/strict";
import {
  THEME_KEY, readTheme, storeTheme, resolveMode, applyTheme, initTheme,
} from "../src/theme.js";

function fakeStorage(initial = {}) {
  const m = new Map(Object.entries(initial));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    dump: () => Object.fromEntries(m),
  };
}

function throwingStorage() {
  return {
    getItem: () => { throw new Error("denied"); },
    setItem: () => { throw new Error("denied"); },
  };
}

function fakeDoc() {
  const attrs = {};
  return {
    body: {
      setAttribute: (k, v) => { attrs[k] = v; },
      removeAttribute: (k) => { delete attrs[k]; },
    },
    attrs,
  };
}

test("readTheme defaults to system for empty, junk, and null storage", () => {
  assert.equal(readTheme(fakeStorage()), "system");
  assert.equal(readTheme(fakeStorage({ [THEME_KEY]: "mauve" })), "system");
  assert.equal(readTheme(null), "system");
});

test("readTheme returns stored explicit choices", () => {
  assert.equal(readTheme(fakeStorage({ [THEME_KEY]: "light" })), "light");
  assert.equal(readTheme(fakeStorage({ [THEME_KEY]: "dark" })), "dark");
});

test("storeTheme then readTheme round-trips", () => {
  const s = fakeStorage();
  assert.equal(storeTheme(s, "light"), true);
  assert.equal(readTheme(s), "light");
  assert.equal(s.dump()[THEME_KEY], "light");
});

test("throwing storage never throws out, reads fall back to system", () => {
  const s = throwingStorage();
  assert.equal(storeTheme(s, "dark"), false);
  assert.equal(readTheme(s), "system");
});

test("resolveMode maps system through the OS preference", () => {
  assert.equal(resolveMode("system", true), "light");
  assert.equal(resolveMode("system", false), "dark");
  assert.equal(resolveMode("light", false), "light");
  assert.equal(resolveMode("dark", true), "dark");
});

test("applyTheme sets the attribute for explicit themes and clears for system", () => {
  const d = fakeDoc();
  applyTheme(d, "light");
  assert.equal(d.attrs["data-vpt"], "light");
  applyTheme(d, "dark");
  assert.equal(d.attrs["data-vpt"], "dark");
  applyTheme(d, "system");
  assert.equal("data-vpt" in d.attrs, false);
});

test("initTheme applies the stored choice before render", () => {
  const d = fakeDoc();
  const t = initTheme(d, fakeStorage({ [THEME_KEY]: "light" }));
  assert.equal(t, "light");
  assert.equal(d.attrs["data-vpt"], "light");
});

test("initTheme with no storage leaves the system default untouched", () => {
  const d = fakeDoc();
  const t = initTheme(d, null);
  assert.equal(t, "system");
  assert.equal("data-vpt" in d.attrs, false);
});
