/* Time rendering — one place, one rule (LOG entry 29).
 *
 * The API serves UTC instants as ISO-8601 strings with explicit offsets
 * ("...T08:00:00+00:00"). Rendering converts to the VIEWER'S local zone and
 * labels the zone explicitly, so "when is this match for me?" is never a
 * guess. If a string ever arrives without an offset, it is treated as UTC:
 * JavaScript's Date would otherwise parse a naive ISO string as LOCAL wall
 * time, silently shifting by the viewer's offset.
 *
 * `opts` exists for tests: pass {locale, timeZone} to get deterministic
 * output. Production callers pass nothing, which means viewer locale and
 * viewer zone.
 */

const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/;

export function parseUtc(iso) {
  if (!iso) return null;
  const s = HAS_OFFSET.test(iso) ? iso : `${iso}Z`;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtTime(iso, opts = {}) {
  const d = parseUtc(iso);
  if (!d) return "—";
  return d.toLocaleString(opts.locale, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    timeZoneName: "short",
    ...(opts.timeZone ? { timeZone: opts.timeZone } : {}),
  });
}
