/* Schedule composition for the v2 page: upcoming groups first (Today,
   Tomorrow, later days, soonest first), then recent results from the
   graded ledger, newest first, limited to the last RESULTS_DAYS
   viewer-local days (ASSUMPTIONS §50). Pure and testable; callers pass
   {now, timeZone, locale} in tests exactly like daygroups. */
import { dayKey, groupByDay } from "./daygroups.js";

export const RESULTS_DAYS = 3;

export function recentResults(graded, opts = {}) {
  const now = opts.now ? new Date(opts.now) : new Date();
  const keep = new Set();
  for (let i = 0; i <= RESULTS_DAYS - 1; i += 1) {
    const d = new Date(now.getTime() - i * 24 * 3600 * 1000);
    keep.add(dayKey(d.toISOString(), opts));
  }
  return (graded || []).filter((r) => keep.has(dayKey(r.start_ts, opts)));
}

export function scheduleGroups(predictions, graded, opts = {}) {
  const up = groupByDay(predictions || [], { dir: "asc", ...opts });
  const res = groupByDay(recentResults(graded, opts),
                         { dir: "desc", ...opts })
    .map((g) => ({ ...g, results: true }));
  return [...up, ...res];
}
