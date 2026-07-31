/* Day grouping for match lists (display only; the API order is untouched).
 *
 * Rules, one place:
 * - Instants come from the API as UTC ISO strings; day boundaries are the
 *   VIEWER'S local midnights, same rule as fmtTime (LOG entry 29).
 * - Future-facing lists sort ascending (soonest first); record-facing
 *   lists sort descending (newest first). The caller picks `dir`.
 * - Rows without a parseable start time sort to the tail in either
 *   direction and group under "unscheduled".
 *
 * `opts` mirrors time.js: pass {locale, timeZone, now} in tests for
 * deterministic output; production callers pass nothing.
 */
import { parseUtc } from "../src/time.js";

export function dayKey(iso, opts = {}) {
  const d = parseUtc(iso);
  if (!d) return null;
  // en-CA renders YYYY-MM-DD, a stable sortable key in any zone.
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric", month: "2-digit", day: "2-digit",
    ...(opts.timeZone ? { timeZone: opts.timeZone } : {}),
  }).format(d);
}

function yearOf(d, opts) {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    ...(opts.timeZone ? { timeZone: opts.timeZone } : {}),
  }).format(d);
}

export function dayLabel(iso, opts = {}) {
  const d = parseUtc(iso);
  if (!d) return "unscheduled";
  const now = opts.now ? parseUtc(opts.now) : new Date();
  const base = d.toLocaleDateString(opts.locale, {
    weekday: "long", month: "short", day: "numeric",
    ...(yearOf(d, opts) !== yearOf(now, opts) ? { year: "numeric" } : {}),
    ...(opts.timeZone ? { timeZone: opts.timeZone } : {}),
  });
  const k = dayKey(iso, opts);
  const DAY = 24 * 3600 * 1000;
  const rel = k === dayKey(now.toISOString(), opts) ? "Today"
    : k === dayKey(new Date(now.getTime() + DAY).toISOString(), opts)
      ? "Tomorrow"
      : k === dayKey(new Date(now.getTime() - DAY).toISOString(), opts)
        ? "Yesterday" : null;
  return rel ? `${rel} \u00b7 ${base}` : base;
}

export function sortByStart(rows, dir = "asc", get = (r) => r.start_ts) {
  const sign = dir === "desc" ? -1 : 1;
  return rows
    .map((r, i) => {
      const d = parseUtc(get(r));
      return { r, i, t: d ? d.getTime() : null };
    })
    .sort((a, b) => {
      if (a.t === null && b.t === null) return a.i - b.i;
      if (a.t === null) return 1;              // tail in either direction
      if (b.t === null) return -1;
      return a.t !== b.t ? sign * (a.t - b.t) : a.i - b.i;   // stable
    })
    .map((x) => x.r);
}

export function groupByDay(rows, opts = {}) {
  const { dir = "asc", get = (r) => r.start_ts, ...fmt } = opts;
  const sorted = sortByStart(rows || [], dir, get);
  const now = fmt.now ? parseUtc(fmt.now) : new Date();
  const todayKey = dayKey(now.toISOString(), fmt);
  const groups = [];
  for (const r of sorted) {
    const key = dayKey(get(r), fmt) || "unscheduled";
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.rows.push(r);
    else groups.push({ key, label: dayLabel(get(r), fmt),
                       isToday: key === todayKey, rows: [r] });
  }
  return groups;
}
