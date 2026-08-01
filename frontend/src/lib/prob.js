/** The one home for probability and percentage strings (ASSUMPTIONS §55).
 *
 * Every surface that shows a probability imports from here; no page rolls
 * its own toFixed. Two invariants this module exists to hold:
 *
 * 1. The SAME side of the SAME frozen probability renders as the SAME
 *    string on every page. `flipProb` reproduces the server's complement
 *    exactly (1 − p at the ledger's 4-decimal precision, the same number
 *    markets.json ships for the opposite side), so a client-side flip and
 *    a server-side flip can never disagree.
 *
 * 2. The favored-team view is one shared rule (team1 iff p >= 0.5), the
 *    same comparison the ledger's own accuracy metric uses.
 *
 * Known, accepted artifact: at 1 dp the two sides of a handful of 4-dp
 * probabilities sum to 99.9% or 100.1% (e.g. 0.1545 -> 15.4% / 84.5%).
 * That is fixed-precision rounding, not data drift; side-identity across
 * surfaces is the invariant worth holding, and both cannot hold at once.
 */

export const fmtPct = (p) => `${(p * 100).toFixed(1)}%`;

/* Ledger-precision complement: mirrors the server's round(1 - p, 4). */
export const flipProb = (p) => Math.round((1 - p) * 1e4) / 1e4;

export const fmtPctOpp = (p) => fmtPct(flipProb(p));

/* Favored-side view of a team1-oriented probability. */
export const favored = (p, team1Name, team2Name) => (p >= 0.5
  ? { name: team1Name, pct: fmtPct(p), team1: true }
  : { name: team2Name, pct: fmtPctOpp(p), team1: false });

/* Signed percent for EV / CLV style numbers, already in percent units.
   Two decimals everywhere, matching the server's own rounding, so a
   masthead and a detail line can never show the same stat differently. */
export const fmtSigned = (v, dp = 2) =>
  `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`;
