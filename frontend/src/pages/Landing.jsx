import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi, fmtPct } from "../lib/useApi.js";
import { fmtTime } from "../time.js";

/* v2 Home: its own fixed dark world, unaffected by the theme toggle
   (ASSUMPTIONS §50). Video hero with the spec's entrance sequence:
   cover fade at .8s, zoom-out 1.16 -> 1.04 over 2.8s, mouse parallax
   ±14/10px, staggered rise for every element. prefers-reduced-motion
   or Save-Data renders the poster and no animation. The next-up strip
   is wired to the first frozen upcoming prediction; every number on
   this page is derived or absent. */

const stillPreferred = () =>
  (typeof window !== "undefined"
    && window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches)
  || (typeof navigator !== "undefined"
      && navigator.connection && navigator.connection.saveData);

function NextUp() {
  const nav = useNavigate();
  const { data } = useApi("/api/upcoming");
  const m = data && data.predictions && data.predictions[0];
  if (!m) return null;
  const fav = m.p_model >= 0.5 ? m.team1_name : m.team2_name;
  const pct = m.p_model >= 0.5 ? m.p_model : 1 - m.p_model;
  return (
    <button type="button" className="home-next rise" style={{ "--d": "1.45s" }}
      onClick={() => nav(`/match/${m.match_id}`)}>
      <span className="home-next-dot" aria-hidden="true" />
      <span className="mono">next up</span>
      <span className="home-next-teams">
        {m.team1_name} vs {m.team2_name}
      </span>
      <span className="mono dim2">{fmtTime(m.start_ts)}</span>
      <span className="home-next-pct">{fmtPct(pct)} {fav}</span>
    </button>
  );
}

export function Landing() {
  const still = stillPreferred();
  const videoRef = useRef(null);
  const wrapRef = useRef(null);
  const [covered, setCovered] = useState(!still);

  useEffect(() => {
    const t = setTimeout(() => setCovered(false), 800);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (still) return undefined;
    const v = videoRef.current;
    const play = () => { if (v && v.paused) v.play().catch(() => {}); };
    const vis = () => { if (!document.hidden) play(); };
    if (v) { v.muted = true; v.defaultMuted = true; v.volume = 0; play(); }
    if (v) v.addEventListener("pause", play);
    document.addEventListener("visibilitychange", vis);
    return () => {
      if (v) v.removeEventListener("pause", play);
      document.removeEventListener("visibilitychange", vis);
    };
  }, [still]);

  useEffect(() => {
    if (still) return undefined;
    const onMove = (e) => {
      const el = wrapRef.current;
      if (!el) return;
      const x = (e.clientX / window.innerWidth - 0.5) * 28;
      const y = (e.clientY / window.innerHeight - 0.5) * 20;
      el.style.setProperty("--px", `${x.toFixed(1)}px`);
      el.style.setProperty("--py", `${y.toFixed(1)}px`);
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [still]);

  return (
    <main className="home">
      <div className="home-media" ref={wrapRef} aria-hidden="true">
        {still ? (
          <div className="home-poster" />
        ) : (
          <video ref={videoRef} className="home-video"
            autoPlay muted loop playsInline
            poster="/hero-poster.jpg">
            <source src="/hero.webm" type="video/webm" />
            <source src="/hero.mp4" type="video/mp4" />
          </video>
        )}
        <div className="home-grade" />
      </div>
      {covered && <div className="home-cover" aria-hidden="true" />}

      <div className="home-stack">
        <svg className="home-mark rise" style={{ "--d": ".5s" }}
          viewBox="0 0 20 20" width="34" height="34" aria-hidden="true">
          <rect x="1.5" y="7" width="11" height="6" rx="1.5" fill="#2fb5a8" />
          <rect x="13.6" y="7" width="5.4" height="6" rx="1.5" fill="#e56a4a" />
        </svg>
        <h1 className="home-wordmark rise" style={{ "--d": ".35s" }}>
          <span className="home-v">v</span>predict
        </h1>
        <div className="home-bar" aria-hidden="true">
          <span className="home-bar-a" /><span className="home-bar-b" />
        </div>
        <p className="home-slogan rise" style={{ "--d": ".9s" }}>
          Visionary by design
        </p>
        <p className="home-tag mono rise" style={{ "--d": "1.05s" }}>
          valorant match predictions &middot; locked before start
        </p>
        <div className="home-ctas rise" style={{ "--d": "1.25s" }}>
          <Link className="home-cta solid" to="/upcoming">
            Schedule <span aria-hidden="true">&rarr;</span>
          </Link>
          <Link className="home-cta ghost" to="/scoreboard">Scoreboard</Link>
        </div>
        <Link className="home-how mono rise" style={{ "--d": "1.35s" }}
          to="/how">how it works</Link>
        <NextUp />
      </div>

      <p className="home-foot mono rise" style={{ "--d": "1.6s" }}>
        data vlr.gg &middot; not affiliated with riot games &middot; not
        betting advice
      </p>
    </main>
  );
}
