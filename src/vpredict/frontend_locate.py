"""Locate the built frontend (frontend/dist) robustly across environments.

Why this exists (LOG entry 12): the old code resolved the dist directory as
``Path(__file__).resolve().parents[3] / "frontend" / "dist"``. That works in a
source checkout, but once the package is pip-installed into site-packages the
same expression points at the Python installation directory, the existence
check fails, and the static mount is silently skipped — the deploy serves 404
at ``/`` with no hint why.

Resolution order (first candidate containing an ``index.html`` wins):

1. ``VPREDICT_FRONTEND_DIR`` environment variable, if set. If it is set but
   invalid (missing dir or no index.html), we log a WARNING naming it and
   still fall through to the other candidates — serving the site beats
   failing on a typo, but the warning makes the misconfiguration visible.
2. ``/app/frontend/dist`` — where the Dockerfile copies the build.
3. ``<ancestor>/frontend/dist`` for every ancestor of this file, nearest
   first. This reproduces the old dev-checkout behaviour without hardcoding
   ``parents[N]``, so it keeps working if the module moves within the tree.
4. ``<cwd>/frontend/dist`` — running from the repo root.

Requiring ``index.html`` (not just the directory) means an empty or
half-built dist is treated as absent rather than mounted and serving 404s.

Returns ``None`` when nothing matches, after logging a WARNING that lists
every path tried — never silent.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vpredict.frontend")

ENV_VAR = "VPREDICT_FRONTEND_DIR"
_CONTAINER_DEFAULT = Path("/app/frontend/dist")


def _valid(candidate: Path) -> bool:
    try:
        return candidate.is_dir() and (candidate / "index.html").is_file()
    except OSError:
        return False


def _candidates() -> list[Path]:
    out: list[Path] = []

    env_val = os.environ.get(ENV_VAR)
    if env_val:
        out.append(Path(env_val))

    out.append(_CONTAINER_DEFAULT)

    here = Path(__file__).resolve()
    for ancestor in here.parents:
        out.append(ancestor / "frontend" / "dist")

    out.append(Path.cwd() / "frontend" / "dist")

    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def locate_frontend_dist() -> Optional[Path]:
    """Return the frontend dist directory, or None (with a WARNING logged)."""
    env_val = os.environ.get(ENV_VAR)
    candidates = _candidates()

    for candidate in candidates:
        if _valid(candidate):
            if env_val and Path(env_val) != candidate:
                logger.warning(
                    "%s is set to %r but that path has no index.html; "
                    "falling back to %s",
                    ENV_VAR,
                    env_val,
                    candidate,
                )
            logger.info("frontend dist located at %s", candidate)
            return candidate

    logger.warning(
        "frontend dist not found; static mount skipped and / will 404. "
        "Tried, in order: %s. Set %s to the built frontend directory "
        "(must contain index.html).",
        ", ".join(str(c) for c in candidates),
        ENV_VAR,
    )
    return None
