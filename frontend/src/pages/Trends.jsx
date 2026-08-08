import React, { useMemo, useState } from "react";
import { useApi, fmtPct } from "../lib/useApi.js";
import { Masthead, MASTHEAD_TIPS } from "../components/Masthead.jsx";

const COLS = [
  ["win_rate", "win %"],
  ["spread_avg", "spread"],
  ["pistol_wr", "pistol %"],
  ["comb_kills_avg", "kills/map"],
  ["fk_diff12", "FK/12"],
];

function mix(m) {
  if (!m) return "n/a";
  const pc = (v) => Math.round((v ?? 0) * 100);
  return `e ${pc(m.elim)} \u00b7 b ${pc(m.boom)} \u00b7 ` +
    `d ${pc(m.defuse)} \u00b7 t ${pc(m.time)}`;
}

export function Trends() {
  const { data, err } = useApi("/api/trends");
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState("spread_avg");
  const [dir, setDir] = useState(-1);
  const teams = data?.teams || [];
  const rows = useMemo(() => {
    const f = q.trim().toLowerCase();
    const out = teams.filter((t) => !f || t.name.toLowerCase().includes(f));
    out.sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return a.name.localeCompare(b.name);
      if (av == null) return 1;
      if (bv == null) return -1;
      return dir * (av - bv) || a.name.localeCompare(b.name);
    });
    return out;
  }, [teams, q, sortKey, dir]);
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading&hellip;</p>;
  const w = data.params?.window_maps ?? 10;
  const onSort = (k) => {
    if (k === sortKey) setDir(-dir);
    else { setSortKey(k); setDir(-1); }
  };
  return (
    <div className="page">
      <Masthead eyebrow="team form windows" tip={MASTHEAD_TIPS.trends}
        title="Trends"
        stats={[{ value: String(data.n_teams ?? teams.length),
                  label: "active teams", tone: "ink" },
                { value: `last ${w}`, label: "maps per team" }]} />
      <p className="note">
        Every number is this team's last {w} completed maps, recomputed
        from stored match pages each refresh. Spread is average round
        margin per map (overtime included); pistols and the method mix
        come from the regulation round strip; kills/map is both teams
        combined; FK/12 is first kills minus first deaths per 12 rounds.
        Teams need {data.params?.min_lifetime_maps ?? 5}+ lifetime maps
        and a completed map in the last {data.params?.active_days ?? 60}
        {" "}days to appear. Descriptive form only, not model features
        and not betting advice.
      </p>
      <p className="note trend-controls">
        <input className="trend-filter" type="text" value={q}
          placeholder="filter teams" aria-label="Filter teams"
          onChange={(e) => setQ(e.target.value)} />
        <span className="dim"> {rows.length} shown &middot; click a
          column to sort</span>
      </p>
      {rows.length === 0 ? (
        <p className="empty">No teams match.</p>
      ) : (
        <div className="table-scroll">
        <table className="ledger">
          <thead>
            <tr>
              <th>team</th><th className="num">maps</th>
              {COLS.map(([k, label]) => (
                <th key={k} className="num">
                  <button type="button" className="th-sort"
                    onClick={() => onSort(k)}>
                    {label}{sortKey === k ? (dir < 0 ? " \u25be" : " \u25b4")
                      : ""}
                  </button>
                </th>
              ))}
              <th>won-round mix</th><th>agents</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.team_id}>
                <td>{t.name}
                  <span className="dim"> &middot; {t.n_lifetime} lifetime</span>
                </td>
                <td className="num">{t.n_window}</td>
                <td className="num">{fmtPct(t.win_rate)}</td>
                <td className={`num ${t.spread_avg >= 0 ? "ok" : "miss"}`}>
                  {t.spread_avg > 0 ? "+" : ""}{t.spread_avg?.toFixed(2)}
                </td>
                <td className="num">{t.pistol_wr == null ? "n/a" : fmtPct(t.pistol_wr)}</td>
                <td className="num">{t.comb_kills_avg?.toFixed(1)}</td>
                <td className="num">{t.fk_diff12 == null ? "n/a"
                  : `${t.fk_diff12 > 0 ? "+" : ""}${t.fk_diff12.toFixed(2)}`}
                </td>
                <td><span className="dim">{mix(t.method_mix)}</span></td>
                <td><span className="dim">
                  {(t.agents_top || []).map((a) => a.agent).join(", ") || "n/a"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      <p className="note">
        Clutch and economy trends are not shown because the store has
        never held their inputs (performance and economy tabs are not
        scraped). They arrive with a future scraping milestone, not as
        estimates.
      </p>
    </div>
  );
}
