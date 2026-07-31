import React, { useEffect } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Mark } from "./components/Mark.jsx";
import { ThemeToggle } from "./components/ThemeToggle.jsx";
import { useApi } from "./lib/useApi.js";
import { Landing } from "./pages/Landing.jsx";
import { Upcoming } from "./pages/Upcoming.jsx";
import { Scoreboard } from "./pages/Scoreboard.jsx";
import { ModelTab } from "./pages/ModelTab.jsx";
import { MarketPicks } from "./pages/MarketPicks.jsx";
import { Backtest } from "./pages/Backtest.jsx";
import { MatchDetail } from "./pages/MatchDetail.jsx";
import { HowItWorks } from "./pages/HowItWorks.jsx";
import { NotFound } from "./pages/NotFound.jsx";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}


function AppFooter() {
  const { data } = useApi("/api/model");
  const v = data && data.version ? `Model ${data.version} \u00b7 ` : "";
  return (
    <footer className="footer mono">
      {v}data from vlr.gg. Predictions lock before each match; the first
      call stands. Not affiliated with Riot Games. Not betting advice.{" "}
      <a className="repo-link" href="https://github.com/ArminObar/valorant-predictor"
        target="_blank" rel="noreferrer">source</a>
    </footer>
  );
}

const TABS = [
  ["upcoming", "schedule"], ["scoreboard", "scoreboard"],
  ["model", "model"], ["markets", "markets"],
  ["backtest", "backtest"], ["how", "how it works"],
];

export default function App() {
  return (
    <>
      <ScrollToTop />
      <div className="topbar">
        <NavLink className="brand" to="/"><Mark /></NavLink>
        <nav className="tabrow">
          {TABS.map(([path, label]) => (
            <NavLink key={path} to={`/${path}`}
              className={({ isActive }) => "tab" + (isActive ? " active" : "")}>
              {label}
            </NavLink>
          ))}
        </nav>
        <span className="theme-pill"><ThemeToggle /></span>
      </div>
      <main className="wrap">
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/upcoming" element={<Upcoming />} />
          <Route path="/scoreboard" element={<Scoreboard />} />
          <Route path="/model" element={<ModelTab />} />
          <Route path="/markets" element={<MarketPicks standalone />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/how" element={<HowItWorks />} />
          <Route path="/match/:id" element={<MatchDetail />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <AppFooter />
    </>
  );
}
