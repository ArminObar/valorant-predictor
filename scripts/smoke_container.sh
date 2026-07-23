#!/usr/bin/env bash
# Container smoke test for vpredict. Regression guard for LOG entries 11 & 12.
#
# What it checks, and which bug class each check catches:
#   1. Builds the image from the COMMITTED tree (`git archive HEAD`), not the
#      working tree — files missing from git (the unanchored `data/`
#      .gitignore bug, entry 11) fail HERE instead of at deploy time.
#   2. Imports every vpredict.* submodule inside the container — catches
#      ModuleNotFoundError for anything not shipped in the wheel.
#   3. Boots the container and asserts:
#        GET /api/health -> 200
#        GET /           -> 200, HTML, non-trivial body
#      — catches the silently-skipped frontend mount (entry 12).
#
# Usage, from the repo root:
#   scripts/smoke_container.sh                 # committed tree (deploy-like)
#   scripts/smoke_container.sh --working-tree  # current files (pre-commit)
#
# Env overrides: IMAGE, HOST_PORT (default 18000), CONTAINER_PORT (8000),
#   PYTHON_BIN (python), VPREDICT_SMOKE_IMPORT_SKIP (comma-sep module names).
# Requires: git, docker, curl. Exits non-zero on any failure.

set -euo pipefail

IMAGE="${IMAGE:-vpredict-smoke}"
HOST_PORT="${HOST_PORT:-18000}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python}"
CONTEXT="committed"
CONTAINER_NAME="vpredict-smoke-run-$$"

for arg in "$@"; do
  case "$arg" in
    --working-tree) CONTEXT="working-tree" ;;
    --committed)    CONTEXT="committed" ;;
    -h|--help)      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "[smoke] unknown arg: $arg" >&2; exit 2 ;;
  esac
done

fail() { echo "[smoke] FAIL: $*" >&2; exit 1; }

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

[ -f Dockerfile ] || fail "run from the repo root (no Dockerfile here)"
command -v docker >/dev/null || fail "docker not found"
command -v curl   >/dev/null || fail "curl not found"

# ---- 1. build ---------------------------------------------------------------
if [ "$CONTEXT" = "committed" ]; then
  command -v git >/dev/null || fail "git not found (needed for committed mode)"
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "[smoke] NOTE: working tree has uncommitted changes; committed mode" \
         "tests HEAD, not what you see in your editor." >&2
  fi
  echo "[smoke] building from committed tree (git archive HEAD)..."
  git archive --format=tar HEAD | docker build -t "$IMAGE" - \
    || fail "docker build (committed tree) failed"
else
  echo "[smoke] building from working tree..."
  docker build -t "$IMAGE" . || fail "docker build (working tree) failed"
fi

# ---- 2. import every submodule ---------------------------------------------
echo "[smoke] importing all vpredict submodules inside the container..."
docker run --rm -i \
  -e "VPREDICT_SMOKE_IMPORT_SKIP=${VPREDICT_SMOKE_IMPORT_SKIP:-}" \
  --entrypoint "$PYTHON_BIN" "$IMAGE" - <<'PY' \
  || fail "module import check failed (see list above)"
import importlib, os, pkgutil, sys

skip = set(filter(None, os.environ.get("VPREDICT_SMOKE_IMPORT_SKIP", "").split(",")))
import vpredict
names = ["vpredict"] + [m.name for m in pkgutil.walk_packages(vpredict.__path__, "vpredict.")]
failed = []
for name in names:
    if name in skip:
        continue
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 — any import failure is the finding
        failed.append((name, f"{type(exc).__name__}: {exc}"))
print(f"[smoke] imported {len(names) - len(failed)}/{len(names)} modules "
      f"({len(skip)} skipped)")
for name, err in failed:
    print(f"[smoke]   FAIL {name}: {err}")
sys.exit(1 if failed else 0)
PY

# ---- 3. boot and probe ------------------------------------------------------
echo "[smoke] starting container (refresh disabled)..."
docker run -d --name "$CONTAINER_NAME" \
  -e "PORT=$CONTAINER_PORT" -e VPREDICT_REFRESH=0 \
  -p "127.0.0.1:${HOST_PORT}:${CONTAINER_PORT}" \
  "$IMAGE" >/dev/null || fail "container failed to start"

BASE="http://127.0.0.1:${HOST_PORT}"
BODY="$(mktemp)"

echo "[smoke] waiting for ${BASE}/api/health ..."
health_ok=0
i=0
while [ "$i" -lt 60 ]; do
  code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$BASE/api/health" || true)"
  if [ "$code" = "200" ]; then health_ok=1; break; fi
  if ! docker ps -q --no-trunc | grep -q "$(docker inspect -f '{{.Id}}' "$CONTAINER_NAME" 2>/dev/null)" ; then
    echo "[smoke] container exited early; last logs:" >&2
    docker logs --tail 50 "$CONTAINER_NAME" >&2 || true
    fail "container died before becoming healthy"
  fi
  i=$((i + 1)); sleep 1
done
if [ "$health_ok" -ne 1 ]; then
  docker logs --tail 50 "$CONTAINER_NAME" >&2 || true
  fail "/api/health did not return 200 within 60s (last code: ${code:-none})"
fi
echo "[smoke] /api/health -> 200"

code="$(curl -s -m 5 -o "$BODY" -w '%{http_code}' "$BASE/")" || true
[ "$code" = "200" ] || {
  docker logs --tail 50 "$CONTAINER_NAME" >&2 || true
  fail "GET / returned ${code:-none}, expected 200 (frontend mount missing? see LOG entry 12)"
}
grep -qiE '<!doctype html|<html' "$BODY" \
  || fail "GET / returned 200 but the body does not look like HTML"
size="$(wc -c < "$BODY" | tr -d ' ')"
[ "$size" -ge 200 ] || fail "GET / body suspiciously small (${size} bytes)"
echo "[smoke] /            -> 200, HTML, ${size} bytes"

rm -f "$BODY"
echo "[smoke] PASS: build ($CONTEXT tree), imports, /api/health, /"
