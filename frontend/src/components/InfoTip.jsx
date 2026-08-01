import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";

export const TIPS = {
  upcoming: "Win probabilities locked at least five minutes before each "
    + "match starts. Once locked, a call never changes.",
  scoreboard: "Every locked call, graded after its match finishes, with an "
    + "Elo baseline scored on the same matches.",
  model: "The exact model serving right now: what it trained on and how "
    + "its probabilities are calibrated.",
  markets: "Locked model probabilities against captured sportsbook prices, "
    + "labeled unvalidated until the preregistered pick count grades. "
    + "Not betting advice.",
  backtest: "A simulated replay of two years of history, retrained on the "
    + "production schedule. Kept apart from the live scoreboard because a "
    + "simulation is not a live record.",
};


export function InfoTip({ tip, label = "about this section" }) {
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  const [pos, setPos] = useState(null);
  const ref = useRef(null);
  const btnRef = useRef(null);
  const popRef = useRef(null);
  // The pop is portaled, so "inside the tooltip" spans two DOM subtrees.
  const within = (n) =>
    Boolean(n && ((ref.current && ref.current.contains(n))
      || (popRef.current && popRef.current.contains(n))));
  useEffect(() => {
    if (!pinned) return undefined;
    const away = (e) => { if (!within(e.target)) setPinned(false); };
    const esc = (e) => { if (e.key === "Escape") setPinned(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [pinned]);
  const open = pinned || hover;
  // Viewport-fixed placement measured from the trigger, clamped to the
  // viewport — and rendered through a portal to document.body. Inside the
  // page tree, any ancestor with a filled transform animation is a
  // containing block for position:fixed (fill-mode holds an IDENTITY
  // MATRIX after from-only keyframes, not `none`), which re-based these
  // coordinates onto the masthead/panel and displaced or buried every
  // pop (LOG entries 48 and 51). document.body never carries transforms,
  // filters, or animations, so the coordinates below always mean the
  // viewport. Guarded by `npm run audit:tips`.
  useLayoutEffect(() => {
    if (!open || !btnRef.current) return;
    const r = btnRef.current.getBoundingClientRect();
    const w = Math.min(280, Math.floor(window.innerWidth * 0.74));
    const left = Math.max(
      8, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 8));
    setPos({ top: r.bottom + 6, left, width: w });
  }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const shut = () => { setHover(false); setPinned(false); };
    window.addEventListener("scroll", shut, true);
    window.addEventListener("resize", shut);
    return () => {
      window.removeEventListener("scroll", shut, true);
      window.removeEventListener("resize", shut);
    };
  }, [open]);
  const focusWithin = (e) => setHover(within(e.target));
  const blurAway = (e) => {
    if (!within(e.relatedTarget)) { setHover(false); setPinned(false); }
  };
  return (
    <span className="infotip" ref={ref}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={focusWithin} onBlur={blurAway}>
      <button type="button" className="i-btn" aria-expanded={open}
        aria-label={label} ref={btnRef}
        onClick={() => setPinned(!pinned)}>i</button>
      {open && pos && createPortal(
        <span className="infotip-pop" role="note" ref={popRef}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          onFocus={focusWithin} onBlur={blurAway}
          style={{ top: pos.top, left: pos.left, width: pos.width }}>
          {tip}{" "}
          <Link className="linklike" to="/how">full story: how it works</Link>
        </span>,
        document.body)}
    </span>
  );
}


export function TitleWithInfo({ title, badge, info }) {
  return (
    <div className="panel-title">
      {title}{badge}
      <InfoTip tip={info} />
    </div>
  );
}
