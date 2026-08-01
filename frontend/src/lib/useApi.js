import { useEffect, useState } from "react";

export function useApi(path) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch(path)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e));
    return () => { alive = false; };
  }, [path]);
  return { data, err };
}

/* Formatting lives in lib/prob.js (the one home for percentage strings);
   re-exported here so existing import paths keep working. */

export { fmtPct, fmtPctOpp, flipProb, favored, fmtSigned } from "./prob.js";
