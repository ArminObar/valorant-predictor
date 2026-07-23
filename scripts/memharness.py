#!/usr/bin/env python3
"""Memory measurement harness for the vpredict refresh cycle. Stdlib only.

Three subcommands:

  run     Measure one command's true peak RSS (the command's whole reaped
          process tree, via wait4) plus, when available, the in-process
          memprof report and the container cgroup peak. Works with ZERO
          changes to the repo; the memprof phase attribution and
          --force-retrain only add detail once their small wiring edits
          (PATCH_NOTES C and F) are applied.

  growth  Run the cycle at several store-size limits and fit peak-vs-N to
          answer "at what match count do we outgrow the budget?". Requires
          wiring edits D (VPREDICT_STORE_LIMIT) and E (VPREDICT_WORKSPACE)
          and ALWAYS runs against a disposable copy of the sandbox dirs —
          a size-limited retrain must never touch the real bundle or
          freeze real ledger predictions. Because the harness cannot
          verify the workspace wiring from outside, growth refuses to run
          without the explicit --i-verified-workspace-wiring flag (the
          verification procedure is in MEMORY_RUNBOOK.md).

  report  Tabulate previously written harness-*.json files side by side.

Nothing here fabricates a number: any reading that is unavailable in the
current environment is reported as null and said so.

Examples
--------
  python scripts/memharness.py run --tag before-mac --force-retrain \
      -- python scripts/refresh.py

  python scripts/memharness.py growth --limits 1700,3400,5100,6796 \
      --force-retrain --sandbox-dirs data --i-verified-workspace-wiring \
      -- python scripts/refresh.py

  python scripts/memharness.py report memprof-out/harness-*.json

POSIX only (macOS / Linux).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MB = 1024 * 1024
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
DEFAULT_BUDGET_MB = 440  # ~85% of the 512 MB Render Starter limit


def _norm_maxrss(ru_maxrss: int) -> int:
    """ru_maxrss is bytes on macOS, kilobytes on Linux."""
    return int(ru_maxrss) if IS_MAC else int(ru_maxrss) * 1024


def _read_first_int(path: str) -> int | None:
    try:
        raw = Path(path).read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return None
    if raw in ("", "max"):
        return None
    try:
        return int(raw.split()[0])
    except ValueError:
        return None


def _cgroup_peak_limit() -> tuple[int | None, int | None]:
    peak = _read_first_int("/sys/fs/cgroup/memory.peak")
    limit = _read_first_int("/sys/fs/cgroup/memory.max")
    if peak is None and limit is None:
        peak = _read_first_int("/sys/fs/cgroup/memory/memory.max_usage_in_bytes")
        limit = _read_first_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    return peak, limit


def _clone_tree(src: Path, dst: Path) -> None:
    """Copy a directory, using filesystem clones where available so a
    multi-GB HTML cache copies in roughly constant time (APFS `cp -c`,
    reflink on Linux). Falls back to a plain copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if IS_MAC:
        cmd = ["cp", "-c", "-R", str(src), str(dst)]
    elif IS_LINUX:
        cmd = ["cp", "-a", "--reflink=auto", str(src), str(dst)]
    else:
        cmd = None
    if cmd is not None:
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return
        except subprocess.CalledProcessError:
            pass  # e.g. non-CoW filesystem — fall through
    shutil.copytree(src, dst)


def _spawn_and_wait(cmd: list[str], env: dict[str, str]) -> tuple[int, int, float]:
    """Run cmd, return (exit_code, peak_rss_bytes_of_reaped_child_tree, secs).

    Uses posix_spawn + wait4 so the rusage belongs to THIS child
    specifically (getrusage(RUSAGE_CHILDREN) would be a cumulative max
    across sequential runs and would poison growth-curve points)."""
    exe = shutil.which(cmd[0])
    if exe is None:
        raise SystemExit(f"[memharness] command not found: {cmd[0]}")
    t0 = time.monotonic()
    pid = os.posix_spawn(exe, cmd, env)
    try:
        _pid, status, ru = os.wait4(pid, 0)
    except KeyboardInterrupt:
        os.kill(pid, 15)
        os.wait4(pid, 0)
        raise
    return (
        os.waitstatus_to_exitcode(status),
        _norm_maxrss(ru.ru_maxrss),
        time.monotonic() - t0,
    )


def measure(
    cmd: list[str],
    tag: str,
    out_dir: Path,
    extra_env: dict[str, str],
    force_retrain: bool,
    budget_mb: float,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    memprof_out = out_dir / f"memprof-{tag}.json"

    env = dict(os.environ)
    env.update(extra_env)
    env["VPREDICT_MEMPROF"] = "1"
    env["VPREDICT_MEMPROF_OUT"] = str(memprof_out)
    if force_retrain:
        env["VPREDICT_FORCE_RETRAIN"] = "1"

    print(f"[memharness] [{tag}] running: {' '.join(cmd)}")
    exit_code, child_peak, dur = _spawn_and_wait(cmd, env)

    memprof_report = None
    if memprof_out.exists():
        try:
            memprof_report = json.loads(memprof_out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[memharness] could not read memprof report: {exc}")
    else:
        print(
            "[memharness] no memprof report — expected until the phase "
            "wiring (PATCH_NOTES edit F) is applied; the wait4 peak below "
            "is still the real number."
        )

    cg_peak, cg_limit = _cgroup_peak_limit()

    peaks = {
        "wait4_child_tree": child_peak,
        "memprof_getrusage": (
            memprof_report["peaks_bytes"]["getrusage_self_max"]
            if memprof_report else None
        ),
        "cgroup_peak": cg_peak,
    }
    binding = max(v for v in peaks.values() if isinstance(v, int))

    result = {
        "tag": tag,
        "cmd": cmd,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "extra_env": {k: extra_env.get(k) for k in sorted(extra_env)},
        "force_retrain": force_retrain,
        "exit_code": exit_code,
        "duration_s": round(dur, 1),
        "peaks_bytes": peaks,
        "cgroup_limit_bytes": cg_limit,
        "budget_mb": budget_mb,
        "within_budget": binding <= budget_mb * MB,
        "memprof_report_path": str(memprof_out) if memprof_report else None,
    }
    (out_dir / f"harness-{tag}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print(
        f"[memharness] [{tag}] exit={exit_code} dur={dur:.0f}s | "
        f"peak (child tree, wait4) = {child_peak / MB:.1f} MB | "
        f"cgroup peak = "
        f"{'n/a' if cg_peak is None else f'{cg_peak / MB:.1f} MB'} | "
        f"budget {budget_mb:.0f} MB → "
        f"{'PASS' if result['within_budget'] else 'OVER'}"
    )
    if exit_code != 0:
        print(f"[memharness] WARNING: command exited non-zero ({exit_code}); "
              f"treat this measurement as suspect.")
    return result


# ---------------------------------------------------------------- growth

def _fit_line(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    a = my - b * mx
    return a, b


def cmd_growth(args: argparse.Namespace, cmd: list[str]) -> int:
    if not args.i_verified_workspace_wiring:
        raise SystemExit(
            "[memharness] growth refused: it runs limited-store retrains, "
            "and if VPREDICT_WORKSPACE (PATCH_NOTES edit E) is not honoured "
            "by the app, those retrains would overwrite the REAL bundle and "
            "freeze garbage predictions into the REAL ledger. Verify the "
            "wiring per MEMORY_RUNBOOK.md step 3a, then re-run with "
            "--i-verified-workspace-wiring."
        )
    limits = [int(x) for x in args.limits.split(",") if x.strip()]
    sandbox_dirs = [Path(d) for d in args.sandbox_dirs.split(",") if d.strip()]
    missing = [d for d in sandbox_dirs if not d.exists()]
    if missing:
        raise SystemExit(
            f"[memharness] sandbox dirs not found from cwd: "
            f"{', '.join(map(str, missing))} — run from the repo root or "
            f"pass --sandbox-dirs."
        )

    out_dir = Path(args.out)
    points: list[dict] = []
    for n in limits:
        ws = Path(tempfile.mkdtemp(prefix=f"vp-growth-{n}-"))
        print(f"[memharness] limit={n}: sandbox workspace {ws}")
        for d in sandbox_dirs:
            _clone_tree(d, ws / d.name)
        extra_env = {
            args.workspace_env: str(ws),
            args.store_limit_env: str(n),
        }
        res = measure(
            cmd, tag=f"growth-{n}", out_dir=out_dir, extra_env=extra_env,
            force_retrain=args.force_retrain, budget_mb=args.budget_mb,
        )
        peak = max(v for v in res["peaks_bytes"].values() if isinstance(v, int))
        points.append({"limit": n, "peak_bytes": peak,
                       "exit_code": res["exit_code"]})
        if args.keep_workspaces:
            print(f"[memharness] kept workspace: {ws}")
        else:
            shutil.rmtree(ws, ignore_errors=True)

    xs = [float(p["limit"]) for p in points]
    ys = [p["peak_bytes"] / MB for p in points]

    print("\n[memharness] growth curve (peak MB vs store limit):")
    for p in points:
        flag = "" if p["exit_code"] == 0 else "  (non-zero exit!)"
        print(f"  {p['limit']:>7} matches → {p['peak_bytes'] / MB:9.1f} MB{flag}")

    summary: dict = {"points": points, "budget_mb": args.budget_mb}
    spread = (max(ys) - min(ys)) / max(ys) if max(ys) > 0 else 0.0
    if len(ys) >= 2 and spread < 0.03:
        print(
            "[memharness] WARNING: peaks vary <3% across limits — "
            f"{args.store_limit_env} is probably not honoured yet "
            "(PATCH_NOTES edit D). The fit below is meaningless until it is."
        )
        summary["store_limit_wiring_suspect"] = True

    fit = _fit_line(xs, ys)
    if fit is not None:
        a, b = fit
        summary["fit"] = {"intercept_mb": a, "slope_mb_per_match": b}
        print(f"[memharness] linear fit: peak ≈ {a:.1f} MB "
              f"+ {b * 1000:.2f} MB per 1000 matches")
        if b > 0:
            crossing = (args.budget_mb - a) / b
            summary["fit"]["budget_crossing_matches"] = crossing
            print(
                f"[memharness] extrapolated {args.budget_mb:.0f} MB budget "
                f"crossing ≈ {crossing:,.0f} matches — an EXTRAPOLATION "
                f"from {len(xs)} measured points, not a measurement."
            )
        else:
            print("[memharness] slope ≤ 0: no budget crossing on this fit.")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "growth-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"[memharness] wrote {out_dir / 'growth-summary.json'}")
    return 0


# ---------------------------------------------------------------- report

def cmd_report(paths: list[str]) -> int:
    rows = []
    for p in paths:
        try:
            rows.append(json.loads(Path(p).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[memharness] skipping {p}: {exc}")
    if not rows:
        raise SystemExit("[memharness] nothing to report")
    print(f"{'tag':<18} {'peak MB':>9} {'cgroup MB':>10} "
          f"{'dur s':>7} {'exit':>5}  within-budget")
    for r in rows:
        peaks = r.get("peaks_bytes", {})
        vals = [v for v in peaks.values() if isinstance(v, int)]
        peak = max(vals) / MB if vals else float("nan")
        cg = peaks.get("cgroup_peak")
        cg_s = f"{cg / MB:.1f}" if isinstance(cg, int) else "n/a"
        print(f"{r.get('tag', '?'):<18} {peak:>9.1f} {cg_s:>10} "
              f"{r.get('duration_s', float('nan')):>7.0f} "
              f"{r.get('exit_code', '?'):>5}  "
              f"{'yes' if r.get('within_budget') else 'NO'}")
    return 0


# ---------------------------------------------------------------- main

def _split_cmd(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def main() -> int:
    own, cmd = _split_cmd(sys.argv[1:])

    ap = argparse.ArgumentParser(
        prog="memharness.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="sub", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--out", default="memprof-out",
                       help="directory for reports (default: ./memprof-out)")
        p.add_argument("--budget-mb", type=float, default=DEFAULT_BUDGET_MB,
                       help=f"pass/fail budget in MB (default "
                            f"{DEFAULT_BUDGET_MB} ≈ 85%% of 512)")
        p.add_argument("--force-retrain", action="store_true",
                       help="set VPREDICT_FORCE_RETRAIN=1 (needs edit C)")

    p_run = sub.add_parser("run", help="measure one command")
    common(p_run)
    p_run.add_argument("--tag", default="run",
                       help="label for the report files")

    p_growth = sub.add_parser("growth", help="peak-vs-store-size curve")
    common(p_growth)
    p_growth.add_argument("--limits", required=True,
                          help="comma-separated match counts, "
                               "e.g. 1700,3400,5100,6796")
    p_growth.add_argument("--sandbox-dirs", default="data",
                          help="comma-separated dirs (relative to cwd) cloned "
                               "into each disposable workspace; include your "
                               "bundle dir if it lives outside data/")
    p_growth.add_argument("--workspace-env", default="VPREDICT_WORKSPACE",
                          help="env var the app reads as its path root "
                               "(edit E; change if you wired a different name)")
    p_growth.add_argument("--store-limit-env", default="VPREDICT_STORE_LIMIT",
                          help="env var capping loaded matches (edit D)")
    p_growth.add_argument("--keep-workspaces", action="store_true")
    p_growth.add_argument("--i-verified-workspace-wiring", action="store_true",
                          help="required safety ack — see MEMORY_RUNBOOK.md")

    p_rep = sub.add_parser("report", help="tabulate harness-*.json files")
    p_rep.add_argument("files", nargs="+")

    args = ap.parse_args(own)

    if args.sub == "report":
        return cmd_report(args.files)
    if not cmd:
        raise SystemExit(
            "[memharness] missing command after `--`, e.g.:  "
            "python scripts/memharness.py run -- python scripts/refresh.py"
        )
    if args.sub == "run":
        measure(cmd, tag=args.tag, out_dir=Path(args.out), extra_env={},
                force_retrain=args.force_retrain, budget_mb=args.budget_mb)
        return 0
    if args.sub == "growth":
        return cmd_growth(args, cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
