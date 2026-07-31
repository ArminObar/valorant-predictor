import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApi, fmtPct } from "../lib/useApi.js";
import { fmtCountdown, fmtTime } from "../time.js";
import { scheduleGroups } from "../scheduleGroups.js";
import { DaySep } from "../components/daybits.jsx";
import { Masthead, MASTHEAD_TIPS } from "../components/Masthead.jsx";

/* v2 Schedule: upcoming groups (Today, Tomorrow, later) then the last
   three days of graded results, per the spec's folded-in design and
   ASSUMPTIONS §50. Card anatomy and the responsive order trick are the
   spec's; every number is derived from the payloads. */

const tri = (name) => (name || "?").replace(/[^A-Za-z0-9]/g, "")
  .slice(0, 3).toUpperCase() || "?";

function Tile({ name, side }) {
  return <span className={`sched-tile ${side}`}>{tri(name)}</span>;
}

function StatusCol({ m, now }) {
  if (m.result) {
    return (
      <div className="sched-status">
        <span className="sched-time dim">{fmtTime(m.start_ts)}</span>
        <span className="sched-chip">final</span>
      </div>
    );
  }
  const started = new Date(m.start_ts).getTime() <= now;
  if (started) {
    return (
      <div className="sched-status">
        <span className="sched-chip live">live</span>
        <span className="sched-time dim">{fmtTime(m.start_ts)}</span>
      </div>
    );
  }
  const cd = fmtCountdown(m.start_ts, now);
  const soon = cd === "starting" || /^in \d+m$/.test(cd || "");
  return (
    <div className="sched-status">
      <span className="sched-time">{fmtTime(m.start_ts)}</span>
      {cd && <span className={"sched-chip" + (soon ? " soon" : "")}>{cd}</span>}
    </div>
  );
}

function Card({ m, now, onOpen }) {
  const favLeft = m.p_model >= 0.5;
  const pct = favLeft ? m.p_model : 1 - m.p_model;
  const favName = favLeft ? m.team1_name : m.team2_name;
  const won = m.result ? m.team1_won === 1 : null;
  const pickRight = m.result
    ? (favLeft ? m.team1_won === 1 : m.team1_won === 0) : null;
  return (
    <div className="sched-card clickable" role="button" tabIndex={0}
      onClick={() => onOpen(m.match_id)}
      onKeyDown={(e) => e.key === "Enter" && onOpen(m.match_id)}>
      <StatusCol m={m} now={now} />
      <div className="sched-pred">
        <span className={"sched-pill " + (favLeft ? "teal" : "ember")}>
          {m.result != null && pickRight != null
            && (pickRight ? "\u2713 " : "\u2717 ")}
          {tri(favName)} {fmtPct(pct)}
        </span>
        {!m.result && (
          <span className="sched-bar" aria-hidden="true">
            <span style={{ width: `${(m.p_model * 100).toFixed(1)}%` }} />
          </span>
        )}
      </div>
      <div className="sched-teams">
        <div className="sched-row">
          <span className={"sched-name left"
            + (favLeft ? " fav" : "")
            + (m.result && won === false ? " lost" : "")}>
            {m.team1_name}
          </span>
          <Tile name={m.team1_name} side="left" />
          {m.result
            ? <span className="sched-score">
                {m.maps_won_1} : {m.maps_won_2}
              </span>
            : <span className="sched-vs">vs</span>}
          <Tile name={m.team2_name} side="right" />
          <span className={"sched-name right"
            + (!favLeft ? " fav" : "")
            + (m.result && won === true ? " lost" : "")}>
            {m.team2_name}
          </span>
        </div>
        <div className="sched-event mono">
          {m.event}{m.best_of ? ` \u00b7 Bo${m.best_of}` : ""}
          {m.low_history && (
            <span className="sched-lowhist"
              title="Fewer than three recorded maps for one team; listed, not scored.">
              low history
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function Upcoming({ onOpen }) {
  const nav = useNavigate();
  const open = onOpen || ((id) => nav(`/match/${id}`));
  const { data, err } = useApi("/api/upcoming");
  const sb = useApi("/api/scoreboard");
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(t);
  }, []);
  if (err) return <p className="note">schedule unavailable right now.</p>;
  if (!data) return <p className="note">loading&hellip;</p>;

  const preds = data.predictions || [];
  const graded = ((sb.data && sb.data.graded) || []).map((r) => ({
    ...r, result: true,
    maps_won_1: r.maps_won_1 ?? r.score1, maps_won_2: r.maps_won_2 ?? r.score2,
  }));
  const acc = sb.data && sb.data.summary && sb.data.summary.model_accuracy;
  const groups = scheduleGroups(preds, graded, {});

  return (
    <div className="page sched">
      <Masthead eyebrow="locked before start" tip={MASTHEAD_TIPS.schedule}
        title="Schedule"
        sub={`Locked at least five minutes before start, frozen after.`
          + (data.model_version ? ` Model ${data.model_version}.` : "")}
        stats={[
          { value: String(preds.length), label: "locked picks" },
          ...(acc != null
            ? [{ value: fmtPct(acc), label: "live accuracy" }] : []),
        ]} />
      {groups.map((g) => (
        <React.Fragment key={(g.results ? "r-" : "u-") + g.key}>
          <DaySep label={g.results ? `Results \u00b7 ${g.label}` : g.label}
            today={g.isToday} />
          {g.rows.map((m) => (
            <Card key={m.match_id} m={m} now={now} onOpen={open} />
          ))}
        </React.Fragment>
      ))}
      <p className="note">
        graded calls live on the scoreboard; the first call stands.
      </p>
    </div>
  );
}
