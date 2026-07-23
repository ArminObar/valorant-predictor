"""Polite, cached, robots-aware fetcher.

Guarantees, by construction:
- robots.txt is fetched and checked before ANY page request; disallowed paths
  raise RobotsDisallowed and nothing is fetched.
- single-threaded, with a hard >= MIN_REQUEST_INTERVAL_S gap between network
  requests (cache hits don't count against the site).
- every fetched page is cached to disk; a cached completed page is never
  re-requested, so the crawler is safely re-runnable.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

from .. import config


class RobotsDisallowed(RuntimeError):
    pass


class PoliteFetcher:
    def __init__(
        self,
        base: str = config.VLR_BASE,
        cache_dir: Path = config.CACHE_DIR,
        min_interval_s: float = config.MIN_REQUEST_INTERVAL_S,
        user_agent: str = config.USER_AGENT,
    ) -> None:
        self.base = base.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval_s = max(1.0, float(min_interval_s))  # floor: never below 1s
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._last_request_t = 0.0
        self._robots: urllib.robotparser.RobotFileParser | None = None
        self.stats = {"network": 0, "cache_hits": 0}

    # ---------------------------------------------------------------- robots
    def _ensure_robots(self) -> urllib.robotparser.RobotFileParser:
        if self._robots is None:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{self.base}/robots.txt"
            try:
                self._throttle()
                resp = self.session.get(robots_url, timeout=20)
                self._last_request_t = time.monotonic()
                self.stats["network"] += 1
                if resp.status_code >= 500:
                    raise RuntimeError(f"robots.txt returned {resp.status_code}")
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    # 4xx (incl. 404): treat as no restrictions, per RFC 9309.
                    rp.parse([])
            except requests.RequestException as e:
                raise RuntimeError(
                    f"Could not fetch {robots_url} ({e}). Refusing to crawl blind — "
                    "check connectivity and retry."
                ) from e
            self._robots = rp
        return self._robots

    def allowed(self, url: str) -> bool:
        return self._ensure_robots().can_fetch(config.USER_AGENT, url)

    # ---------------------------------------------------------------- cache
    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.json"

    def cached(self, url: str) -> str | None:
        p = self._cache_path(url)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))["body"]
        return None

    def _write_cache(self, url: str, body: str) -> None:
        p = self._cache_path(url)
        p.write_text(json.dumps({"url": url, "fetched_at": time.time(), "body": body}),
                     encoding="utf-8")

    def cache_age_s(self, url: str) -> float | None:
        p = self._cache_path(url)
        if not p.exists():
            return None
        return time.time() - json.loads(p.read_text(encoding="utf-8"))["fetched_at"]

    # ---------------------------------------------------------------- fetch
    def _throttle(self) -> None:
        wait = self.min_interval_s - (time.monotonic() - self._last_request_t)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, *, max_cache_age_s: float | None = None) -> str:
        """Return page body. Serves from cache unless missing or older than
        max_cache_age_s (None = cache never expires)."""
        if urlparse(url).netloc != urlparse(self.base).netloc:
            raise ValueError(f"Fetcher is scoped to {self.base}, got {url}")
        age = self.cache_age_s(url)
        if age is not None and (max_cache_age_s is None or age <= max_cache_age_s):
            self.stats["cache_hits"] += 1
            return self.cached(url)  # type: ignore[return-value]

        if not self.allowed(url):
            raise RobotsDisallowed(
                f"robots.txt disallows {url} for our user agent. Per the project "
                "rules, do not fetch it — switch data source (see ASSUMPTIONS.md)."
            )
        self._throttle()
        resp = self.session.get(url, timeout=30)
        self._last_request_t = time.monotonic()
        self.stats["network"] += 1
        resp.raise_for_status()
        self._write_cache(url, resp.text)
        return resp.text
