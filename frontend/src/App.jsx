import React, { useEffect } from "react";
import { NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { Mark } from "./components/Mark.jsx";
import { ThemeToggle } from "./components/ThemeToggle.jsx";
import { useApi } from "./lib/useApi.js";
import { Landing } from "./pages/Landing.jsx";
import { Upcoming } from "./pages/Upcoming.jsx";
import { Scoreboard } from "./pages/Scoreboard.jsx";
import { ModelTab } from "./pages/ModelTab.jsx";
import { MarketPicks } from "./pages/MarketPicks.jsx";
import { Trends } from "./pages/Trends.jsx";
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
  ["trends", "trends"], ["backtest", "backtest"],
  ["how", "how it works"],
];

/* Interior shell: sticky topbar, centered column, footer. Home sits
   outside it on purpose: the spec's landing is its own full-viewport
   dark world with no interior chrome (ASSUMPTIONS §53). Schedule runs
   the spec's 1000px column; every other interior page gets 1040px. */
function Shell() {
  const { pathname } = useLocation();
  const wrapClass = "wrap" + (pathname === "/upcoming" ? " wrap-sched" : "");
  return (
    <>
      <div className="topbar">
        <NavLink className="brand" to="/">
          <Mark size={20} />
          <span className="logo"><span className="logo-accent">v</span>predict</span>
        </NavLink>
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
      <main className={wrapClass}><Outlet /></main>
      <AppFooter />
    </>
  );
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route element={<Shell />}>
          <Route path="/upcoming" element={<Upcoming />} />
          <Route path="/scoreboard" element={<Scoreboard />} />
          <Route path="/model" element={<ModelTab />} />
          <Route path="/markets" element={<MarketPicks standalone />} />
          <Route path="/trends" element={<Trends />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/how" element={<HowItWorks />} />
          <Route path="/match/:id" element={<MatchDetail />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </>
  );
}
