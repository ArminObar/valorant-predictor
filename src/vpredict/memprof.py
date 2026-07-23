"""Lightweight memory instrumentation for the refresh cycle. Stdlib only.

Activation
----------
Inert unless ``VPREDICT_MEMPROF=1`` is set in the environment, so the
``with phase("...")`` wrappers can stay in production code permanently at
zero cost. When active, a daemon thread samples this process's RSS, phases
are tagged, and a JSON report is written at interpreter exit.

Environment knobs (all optional):

- ``VPREDICT_MEMPROF=1``            enable
- ``VPREDICT_MEMPROF_OUT=path.json`` report path (default ./memprof-<ts>-<pid>.json)
- ``VPREDICT_MEMPROF_INTERVAL=0.25`` sample interval seconds
  (default 0.25 on Linux; 1.0 on macOS, where each sample shells out to ``ps``)
- ``VPREDICT_MEMPROF_TRACEMALLOC=1`` also record per-phase top Python
  allocation sites via tracemalloc (Python-side only — numpy/LightGBM
  native buffers are invisible to it; slows the run noticeably)
- ``VPREDICT_MEMPROF_SAMPLES=full``  keep the full sample series in the
  report instead of downsampling to ~4000 points

What the report contains
------------------------
- peaks: getrusage max RSS (self), /proc VmHWM (Linux), cgroup v2/v1 peak
  and limit when running in a container, and the max of the sampled series.
  On Render the cgroup numbers are the binding ones.
- phases: enter/exit RSS and HWM, duration, and the sampled peak inside
  each phase's time window.
- a small allowlisted env fingerprint (store limit, force-retrain,
  workspace) so measurement runs are self-documenting.

Units: everything in the report is bytes; the stderr summary prints MB.
Platform notes: ``ru_maxrss`` is bytes on macOS and kilobytes on Linux —
normalised here. Child processes are NOT covered by this module; the
harness (scripts/memharness.py) measures the child tree via wait4.
"""
from __future__ import annotations

import atexit
import json
import os
import platform
import resource
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_IS_LINUX = sys.platform.startswith("linux")
_IS_MAC = sys.platform == "darwin"

_ENABLED = os.environ.get("VPREDICT_MEMPROF") == "1"
_TRACEMALLOC = _ENABLED and os.environ.get("VPREDICT_MEMPROF_TRACEMALLOC") == "1"

_ENV_ALLOWLIST = (
    "VPREDICT_STORE_LIMIT",
    "VPREDICT_FORCE_RETRAIN",
    "VPREDICT_WORKSPACE",
    "VPREDICT_REFRESH",
)

_MB = 1024 * 1024


def enabled() -> bool:
    return _ENABLED


# ---------------------------------------------------------------- readers

def _maxrss_self_bytes() -> int:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(ru) if _IS_MAC else int(ru) * 1024


def _proc_status_bytes(field: str) -> int | None:
    """Read VmRSS / VmHWM (kB) from /proc/self/status. Linux only."""
    if not _IS_LINUX:
        return None
    try:
        with open("/proc/self/status", "r", encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith(field + ":"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _rss_now_bytes() -> int | None:
    if _IS_LINUX:
        return _proc_status_bytes("VmRSS")
    if _IS_MAC:
        try:
            out = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            return int(out) * 1024 if out else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return None


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


def cgroup_memory() -> dict:
    """Current / peak / limit for this container's cgroup, values in bytes.

    cgroup v2 first, then v1. All fields None outside a limited container
    (or where the kernel doesn't expose memory.peak).
    """
    v2 = {
        "current": _read_first_int("/sys/fs/cgroup/memory.current"),
        "peak": _read_first_int("/sys/fs/cgroup/memory.peak"),
        "limit": _read_first_int("/sys/fs/cgroup/memory.max"),
        "version": "v2",
    }
    if any(v2[k] is not None for k in ("current", "peak", "limit")):
        return v2
    v1 = {
        "current": _read_first_int("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
        "peak": _read_first_int("/sys/fs/cgroup/memory/memory.max_usage_in_bytes"),
        "limit": _read_first_int("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
        "version": "v1",
    }
    if any(v1[k] is not None for k in ("current", "peak", "limit")):
        return v1
    return {"current": None, "peak": None, "limit": None, "version": None}


# ---------------------------------------------------------------- state

_T0 = time.monotonic()
_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%S%z")
_samples: list[tuple[float, int, str]] = []      # (t_rel, rss_bytes, phase_path)
_phases: list[dict] = []
_phase_stack: list[str] = []
_stop = threading.Event()
_sampler: threading.Thread | None = None
_written = False


def _sample_once() -> None:
    rss = _rss_now_bytes()
    if rss is not None:
        _samples.append((time.monotonic() - _T0, rss, "/".join(_phase_stack)))


def _sampler_loop(interval: float) -> None:
    while not _stop.is_set():
        _sample_once()
        # Bound memory used by the profiler itself on very long runs.
        if len(_samples) > 400_000:
            interval *= 2
            del _samples[::2]
        _stop.wait(interval)
    _sample_once()


def _start() -> None:
    global _sampler
    if _TRACEMALLOC:
        import tracemalloc
        tracemalloc.start(10)
    default_interval = 0.25 if _IS_LINUX else 1.0
    try:
        interval = float(os.environ.get("VPREDICT_MEMPROF_INTERVAL", default_interval))
    except ValueError:
        interval = default_interval
    _sample_once()
    _sampler = threading.Thread(
        target=_sampler_loop, args=(max(interval, 0.05),),
        name="vpredict-memprof", daemon=True,
    )
    _sampler.start()
    atexit.register(write_report)


# ---------------------------------------------------------------- API

@contextmanager
def phase(name: str):
    """Tag a stage of the pipeline. No-op unless VPREDICT_MEMPROF=1."""
    if not _ENABLED:
        yield
        return
    _phase_stack.append(name)
    path = "/".join(_phase_stack)
    rec: dict = {
        "name": name,
        "path": path,
        "t_start": time.monotonic() - _T0,
        "rss_enter": _rss_now_bytes(),
        "hwm_enter": _proc_status_bytes("VmHWM") or _maxrss_self_bytes(),
    }
    if _TRACEMALLOC:
        import tracemalloc
        rec["_tm_enter"] = tracemalloc.take_snapshot()
    try:
        yield
    finally:
        rec["t_end"] = time.monotonic() - _T0
        rec["rss_exit"] = _rss_now_bytes()
        rec["hwm_exit"] = _proc_status_bytes("VmHWM") or _maxrss_self_bytes()
        if _TRACEMALLOC:
            import tracemalloc
            snap = tracemalloc.take_snapshot()
            stats = snap.compare_to(rec.pop("_tm_enter"), "lineno")[:15]
            rec["tracemalloc_top"] = [
                {
                    "site": str(s.traceback),
                    "size_diff_bytes": s.size_diff,
                    "size_bytes": s.size,
                }
                for s in stats
            ]
        _phases.append(rec)
        _phase_stack.pop()


def snapshot(label: str) -> None:
    """Record a labelled point-in-time RSS reading."""
    if not _ENABLED:
        return
    rss = _rss_now_bytes()
    _phases.append({
        "name": f"snapshot:{label}",
        "path": "/".join(_phase_stack),
        "t_start": time.monotonic() - _T0,
        "t_end": time.monotonic() - _T0,
        "rss_enter": rss,
        "rss_exit": rss,
        "hwm_enter": _proc_status_bytes("VmHWM") or _maxrss_self_bytes(),
        "hwm_exit": _proc_status_bytes("VmHWM") or _maxrss_self_bytes(),
    })


def _phase_sampled_peak(rec: dict) -> int | None:
    window = [
        rss for (t, rss, _tag) in _samples
        if rec["t_start"] <= t <= rec.get("t_end", rec["t_start"])
    ]
    return max(window) if window else None


def write_report() -> Path | None:
    """Write the JSON report (normally called automatically at exit)."""
    global _written
    if not _ENABLED or _written:
        return None
    _written = True
    _stop.set()
    if _sampler is not None:
        _sampler.join(timeout=5)

    for rec in _phases:
        rec["sampled_peak"] = _phase_sampled_peak(rec)

    sampled_max = max((rss for (_t, rss, _tag) in _samples), default=None)

    series: list = list(_samples)
    if os.environ.get("VPREDICT_MEMPROF_SAMPLES") != "full" and len(series) > 4000:
        stride = len(series) // 4000 + 1
        series = series[::stride]

    report = {
        "meta": {
            "pid": os.getpid(),
            "argv": sys.argv,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "started_at": _STARTED_AT,
            "duration_s": round(time.monotonic() - _T0, 3),
            "env": {k: os.environ.get(k) for k in _ENV_ALLOWLIST
                    if os.environ.get(k) is not None},
        },
        "peaks_bytes": {
            "getrusage_self_max": _maxrss_self_bytes(),
            "vmhwm": _proc_status_bytes("VmHWM"),
            "cgroup_peak": cgroup_memory().get("peak"),
            "sampled_max": sampled_max,
        },
        "cgroup": cgroup_memory(),
        "phases": _phases,
        "samples": [
            {"t": round(t, 3), "rss": rss, "phase": tag} for (t, rss, tag) in series
        ],
    }

    out = os.environ.get("VPREDICT_MEMPROF_OUT") or (
        f"memprof-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.json"
    )
    out_path = Path(out)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        peak = max(
            v for v in report["peaks_bytes"].values() if isinstance(v, int)
        )
        print(
            f"[memprof] peak ~{peak / _MB:.1f} MB "
            f"(getrusage {report['peaks_bytes']['getrusage_self_max'] / _MB:.1f} MB) "
            f"— report: {out_path}",
            file=sys.stderr,
        )
        return out_path
    except OSError as exc:  # never let reporting kill the pipeline
        print(f"[memprof] failed to write report: {exc}", file=sys.stderr)
        return None


if _ENABLED:
    _start()
