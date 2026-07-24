#!/usr/bin/env python3
"""One full refresh cycle (crawl -> grade -> retrain if stale -> predict).
Cron this on any box with its own disk; on Render/Railway the in-process
scheduler (VPREDICT_REFRESH=1) spawns the same entrypoint as a subprocess.
Thin wrapper: the real CLI lives in vpredict.serving.refresh so cron and the
scheduler share one entrypoint (`python -m vpredict.serving.refresh`)."""
from vpredict.serving.refresh import main

if __name__ == "__main__":
    raise SystemExit(main())
