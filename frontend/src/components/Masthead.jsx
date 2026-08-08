import React from "react";
import { InfoTip } from "./InfoTip.jsx";

/* Page masthead per the v2 spec: open editorial block above a hairline.
   Eyebrow (+ optional warn variant for Backtest), one info tooltip per
   page (spec copy; the Markets line is corrected on record in
   ASSUMPTIONS §50 because picks list regardless of EV sign), huge
   title, derived stat slots on the right. */
export const MASTHEAD_TIPS = {
  schedule: "Upcoming matches with the model's locked win probability "
    + "for each. Click any match for the full breakdown.",
  scoreboard: "The running record: every locked call, graded right or "
    + "wrong once the match ends. Nothing is edited after the fact.",
  model: "What feeds the predictions: team ratings, map form, and the "
    + "training and versioning behind the current model.",
  markets: "The model's probability set against sportsbook prices. "
    + "Every pick lists with its expected value at the captured entry "
    + "price, positive or negative.",
  trends: "Descriptive form windows per team: spreads, pistols, "
    + "combined kills, round win methods, and agent picks over the "
    + "last ten completed maps. Not model features.",
  backtest: "A replay of the past two years as if the model had been "
    + "live the whole time. Simulated results only; the real record "
    + "lives on the scoreboard.",
};

export function Masthead({ eyebrow, warn, tip, title, sub, stats }) {
  return (
    <header className="masthead">
      <div className="mh-eyebrow-row">
        <span className={"mh-eyebrow" + (warn ? " warn" : "")}>{eyebrow}</span>
        {tip && <InfoTip tip={tip} label={`about ${eyebrow}`} />}
      </div>
      <div className="mh-main">
        <h1 className="mh-title">{title}</h1>
        {stats && stats.length > 0 && (
          <div className="mh-stats">
            {stats.map((s) => (
              <div className="mh-stat" key={s.label}>
                <span className={"mh-val" + (s.tone ? ` ${s.tone}` : "")}>
                  {s.value}
                </span>
                <span className="mh-label">{s.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {sub && <p className="mh-sub">{sub}</p>}
    </header>
  );
}
