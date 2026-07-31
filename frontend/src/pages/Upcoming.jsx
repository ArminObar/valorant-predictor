import React from "react";
import { useApi, fmtPct } from "../lib/useApi.js";
import { fmtTime } from "../time.js";
import { groupByDay } from "../daygroups.js";
import { DaySep } from "../components/daybits.jsx";
import { InfoTip, TIPS } from "../components/InfoTip.jsx";

export function UpcomingCard({ m, onOpen }) {
  const p = m.p_model;
  const fav = p >= 0.5 ? m.team1_name : m.team2_name;
  const eta = fmtEta(m.start_ts);
  const soon = eta && eta !== null && !eta.endsWith("d");
  return (
    <div className="card clickable" role="button" tabIndex={0}
      onClick={() => onOpen(m.match_id)}
      onKeyDown={(e) => e.key === "Enter" && onOpen(m.match_id)}>
      <div className="card-top">
        <span className="event">{m.event}</span>
        <span className="when">
          {eta && <span className={`eta${soon ? " soon" : ""}`}>{eta}</span>}
          {fmtTime(m.start_ts)} &middot; Bo{m.best_of}
        </span>
      </div>
      <div className="teams">
        <span className={`team a ${p >= 0.5 ? "fav" : ""}`}>
          <Tile name={m.team1_name} side="a" />{m.team1_name}</span>
        <span className="vs">vs</span>
        <span className={`team b ${p < 0.5 ? "fav" : ""}`}>
          {m.team2_name}<Tile name={m.team2_name} side="b" /></span>
      </div>
      <TugBar p={p} />
      <div className="probs">
        <span className="num a">{fmtPct(p)}</span>
        <span className="mid">
          pick <b>{fav}</b> &middot; Elo {fmtPct(m.p_elo)}
          {m.low_history ? (
            <span className="badge" title={"Fewer than 3 recorded maps "
              + "for one or both teams, so this leans on defaults. "
              + "Trust it less."}>low history</span>
          ) : null}
        </span>
        <span className="num b">{fmtPct(1 - p)}</span>
      </div>
    </div>
  );
}


export function Upcoming({ onOpen }) {
  const { data, err } = useApi("/api/upcoming");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading&hellip;</p>;
  if (!data.predictions.length)
    return (
      <p className="empty">
        No upcoming predictions right now. New ones appear after the next
        refresh cycle.
      </p>
    );
  return (
    <>
      <div className="page-head">
        <h1>Upcoming<InfoTip tip={TIPS.upcoming} label="about upcoming" /></h1>
        <span className="page-sub">{data.predictions.length} locked predictions</span>
      </div>
      <p className="note">
        Locked at least five minutes before start. Frozen after.
        Model {data.model_version}, generated {fmtTime(data.generated_at)}.
      </p>
      {groupByDay(data.predictions, { dir: "asc" }).map((g) => (
        <React.Fragment key={g.key}>
          <DaySep label={g.label} today={g.isToday} />
          {g.rows.map((m) => (
            <UpcomingCard key={m.match_id} m={m} onOpen={onOpen} />
          ))}
        </React.Fragment>
      ))}
    </>
  );
}
