"""The recent-window results summary artifact — schema and gatekeeping.

`scripts/evaluate.py` writes `results_summary.json` next to `results.md`,
built from the SAME in-scope variables that populate the markdown tables,
so the JSON cannot drift from the report. `scripts/publish_results.py`
moves that artifact to the live site (never computing or editing a
metric), and `validate_summary` is the gate both the publisher and the
tests use: nothing synthetic and nothing structurally incomplete may
reach the public site (ASSUMPTIONS §6, §22).
"""
from __future__ import annotations

REQUIRED_KEYS = ("generated_at", "source", "store", "split", "selected",
                 "map", "series", "per_tier")


def validate_summary(report) -> list[str]:
    """Return human-readable refusal reasons; an empty list means valid."""
    if not isinstance(report, dict):
        return ["summary is not a JSON object"]
    problems: list[str] = []
    if report.get("synthetic"):
        problems.append(
            "summary is watermarked synthetic — synthetic numbers never "
            "reach the public site (ASSUMPTIONS §6)")
    for k in REQUIRED_KEYS:
        if k not in report:
            problems.append(f"missing required key '{k}'")
    for grain in ("map", "series"):
        g = report.get(grain)
        if not isinstance(g, dict):
            continue                     # already reported as missing above
        for side in ("model", "elo"):
            block = g.get(side)
            if not isinstance(block, dict) or block.get("log_loss") is None:
                problems.append(f"{grain}.{side}.log_loss missing")
    return problems
