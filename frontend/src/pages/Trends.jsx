import React, { useMemo, useState } from "react";
import { useApi, fmtPct } from "../lib/useApi.js";
import { Masthead, MASTHEAD_TIPS } from "../components/Masthead.jsx";

const COLS = [
  ["n_window", "maps"],
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

function scopeLine(view, tournaments) {
  const s = view?.scope || {};
  if (s.preset === "current_form")
    return "Current form: each team's last 10 maps, active in the " +
      "last 60 days.";
  if (s.preset === "custom") {
    const bits = [];
    if (s.from || s.to)
      bits.push(`${s.from || "start of data"} to ${s.to || "today"}`);
    if (s.event) bits.push(s.event);
    return `Custom scope: ${bits.join(", ") || "all data"}. All maps in ` +
      "scope per team.";
  }
  const n = tournaments?.length;
  return "All real scraped history" + (n ? ` across ${n} tournaments`
    : "") + ". All maps per team.";
}

export function Trends() {
  const [preset, setPreset] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [eventName, setEventName] = useState("");
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState("n_window");
  const [dir, setDir] = useState(-1);

  const custom = Boolean(from || to || eventName.trim());
  const url = custom
    ? `/api/trends?${new URLSearchParams({
        ...(from && { from }), ...(to && { to }),
        ...(eventName.trim() && { event: eventName.trim() }),
      })}`
    : preset === "current" ? "/api/trends?preset=current_form"
      : "/api/trends";
  const { data, err } = useApi(url);

  const view = data?.view;
  const teams = view?.teams || [];
  const tournaments = data?.tournaments || [];
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
  const onSort = (k) => {
    if (k === sortKey) setDir(-dir);
    else { setSortKey(k); setDir(-1); }
  };
  const clearScope = () => { setFrom(""); setTo(""); setEventName(""); };
  return (
    <div className="page">
      <Masthead eyebrow="team form, any scope" tip={MASTHEAD_TIPS.trends}
        title="Trends"
        stats={[{ value: String(view?.n_teams ?? teams.length),
                  label: "teams in scope", tone: "ink" },
                { value: custom ? "custom" : (preset === "current"
                  ? "form" : "all"), label: "scope" }]} />
      <p className="note">
        Every number aggregates the maps inside the selected scope,
        recomputed from stored match pages. Spread is average round
        margin per map (overtime included); pistols and the method mix
        come from the regulation round strip; kills/map is both teams
        combined; FK/12 is first kills minus first deaths per 12 rounds.
        A map missing a metric's inputs is left out of that metric
        entirely, numerator and denominator, and a team with nothing
        left shows n/a: nothing is estimated or zero-filled. Teams need
        {" "}{data.params?.scope_min_maps ?? 5}+ maps in scope to
        appear. Descriptive form only, not model features and not
        betting advice.
      </p>
      <p className="note trend-controls">
        <button type="button"
          className={`trend-preset${!custom && preset === "all"
            ? " active" : ""}`}
          onClick={() => { clearScope(); setPreset("all"); }}>
          all history</button>
        <button type="button"
          className={`trend-preset${!custom && preset === "current"
            ? " active" : ""}`}
          onClick={() => { clearScope(); setPreset("current"); }}>
          current form</button>
        <input className="trend-filter" type="date" value={from}
          aria-label="From date" onChange={(e) => setFrom(e.target.value)} />
        <input className="trend-filter" type="date" value={to}
          aria-label="To date" onChange={(e) => setTo(e.target.value)} />
        <input className="trend-filter" type="text" value={eventName}
          list="trend-tournaments" placeholder="tournament"
          aria-label="Tournament"
          onChange={(e) => setEventName(e.target.value)} />
        <datalist id="trend-tournaments">
          {tournaments.map((t) => (
            <option key={t.id} value={t.name}>
              {`${t.n_matches} matches`}</option>
          ))}
        </datalist>
        <input className="trend-filter" type="text" value={q}
          placeholder="filter teams" aria-label="Filter teams"
          onChange={(e) => setQ(e.target.value)} />
      </p>
      <p className="note">
        <span className="dim">{scopeLine(view, tournaments)} {rows.length}
        {" "}shown &middot; click a column to sort.</span>
      </p>
      {rows.length === 0 ? (
        <p className="empty">
          No teams match this scope. Data covers scraped completed
          matches only; scopes outside it are simply empty.
        </p>
      ) : (
        <div className="table-scroll">
        <table className="ledger">
          <thead>
            <tr>
              <th>team</th>
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
                <td className="num">{t.pistol_wr == null ? "n/a"
                  : fmtPct(t.pistol_wr)}</td>
                <td className="num">{t.comb_kills_avg == null ? "n/a"
                  : t.comb_kills_avg.toFixed(1)}</td>
                <td className="num">{t.fk_diff12 == null ? "n/a"
                  : `${t.fk_diff12 > 0 ? "+" : ""}${t.fk_diff12.toFixed(2)}`}
                </td>
                <td><span className="dim">{mix(t.method_mix)}</span></td>
                <td><span className="dim">
                  {(t.agents_top || []).map((a) => a.agent).join(", ")
                    || "n/a"}</span></td>
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
