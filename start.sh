#!/usr/bin/env bash
# start.sh — launches the Spotlight backend and frontend together.
#
# Usage:
#   ./start.sh          # normal mode
#   DEBUG=true ./start.sh   # enable debug-level logging in the backend
#
# Logs are written (and tailed) to:
#   logs/backend.log
#   logs/frontend.log
#
# Press Ctrl+C to stop both services cleanly.

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$ROOT_DIR/logs"
BACKEND_LOG="$LOGS_DIR/backend.log"
FRONTEND_LOG="$LOGS_DIR/frontend.log"
VENV_PYTHON="$ROOT_DIR/venv/bin/python"

# ── Colours (disabled when not a tty) ─────────────────────────────────────────
if [ -t 1 ]; then
    BOLD='\033[1m'; RESET='\033[0m'
    GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'
else
    BOLD=''; RESET=''; GREEN=''; YELLOW=''; RED=''; CYAN=''
fi

log()  { echo -e "${BOLD}$*${RESET}"; }
ok()   { echo -e "${GREEN}✔ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠ $*${RESET}"; }
err()  { echo -e "${RED}✖ $*${RESET}" >&2; }

# ── Load .env into the shell environment ──────────────────────────────────────
# This makes every KEY=VALUE in .env available to both child processes.
# Lines starting with # and blank lines are skipped.
# Values already set in the calling shell take precedence (set -u safe).
ENV_FILE="$ROOT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    ok "Loading environment from .env"
    # Export each non-comment, non-blank line; strip inline comments and quotes.
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip blank lines and comments
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        # Strip leading "export " if present
        line="${line#export }"
        # Only process lines that look like KEY=VALUE
        [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
        # Don't override variables already set in the calling environment
        key="${line%%=*}"
        val="${line#*=}"
        # Strip surrounding single or double quotes from the value
        val="${val%\'}" ; val="${val#\'}"
        val="${val%\"}" ; val="${val#\"}"
        if [ -z "${!key+x}" ]; then
            export "$key=$val"
        fi
    done < "$ENV_FILE"
else
    warn ".env file not found — continuing without it (some features may not work)"
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if [ ! -f "$VENV_PYTHON" ]; then
    err "Virtual environment not found at $ROOT_DIR/venv"
    err "Run ./setup.sh first."
    exit 1
fi

if ! command -v npm &>/dev/null; then
    err "npm not found — install Node.js first (brew install node)."
    exit 1
fi

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
    warn "frontend/node_modules missing — running npm install…"
    (cd "$ROOT_DIR/frontend" && npm install)
fi

# ── Log setup ─────────────────────────────────────────────────────────────────
mkdir -p "$LOGS_DIR"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
DIVIDER="════════════════════════════════════════════════════════"

for f in "$BACKEND_LOG" "$FRONTEND_LOG"; do
    printf '%s\n Started: %s\n%s\n\n' "$DIVIDER" "$TIMESTAMP" "$DIVIDER" > "$f"
done

# ── Start backend ─────────────────────────────────────────────────────────────
log "\n${CYAN}▶ Backend${RESET}  — http://localhost:8080  (log → logs/backend.log)"

(
    cd "$ROOT_DIR/backend"
    # Unset PORT so uvicorn is controlled solely by --port, not the env var
    unset PORT
    exec "$VENV_PYTHON" -m uvicorn app:app \
        --host 0.0.0.0 \
        --port 8080 \
        --reload \
        --log-level "$([ "${DEBUG:-false}" = "true" ] && echo debug || echo info)"
) >> "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Give the backend a moment to bind before starting the frontend
sleep 1

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    err "Backend failed to start — check $BACKEND_LOG"
    exit 1
fi
ok "Backend started (PID $BACKEND_PID)"

# ── Start frontend ────────────────────────────────────────────────────────────
log "${CYAN}▶ Frontend${RESET} — http://localhost:3000  (log → logs/frontend.log)"

(
    cd "$ROOT_DIR/frontend"
    # Pin to port 3000 explicitly — overrides any PORT set in .env
    # BROWSER=none suppresses the auto-open so the user can open it manually
    exec env PORT=3000 BROWSER=none npm start
) >> "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

sleep 2

if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    err "Frontend failed to start — check $FRONTEND_LOG"
    kill "$BACKEND_PID" 2>/dev/null || true
    exit 1
fi
ok "Frontend started (PID $FRONTEND_PID)"

# ── Cleanup handler ───────────────────────────────────────────────────────────
cleanup() {
    echo ""
    log "Shutting down both services…"
    kill "$BACKEND_PID"  2>/dev/null || true
    kill "$FRONTEND_PID" 2>/dev/null || true
    # Give processes a moment to exit gracefully before we leave
    sleep 1
    ok "Done. Full logs are in $LOGS_DIR"
    exit 0
}
trap cleanup INT TERM

# ── Tail both log files to the terminal ───────────────────────────────────────
echo ""
log "Both services running. Press ${BOLD}Ctrl+C${RESET} to stop.\n"
echo -e "${CYAN}${DIVIDER}${RESET}"

# tail -f on two files interleaves output with headers:
#   ==> logs/backend.log <==
#   ==> logs/frontend.log <==
tail -f "$BACKEND_LOG" "$FRONTEND_LOG" &
TAIL_PID=$!

# Stay alive until either service exits unexpectedly
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 2
done

kill "$TAIL_PID" 2>/dev/null || true

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    err "Backend exited unexpectedly — check $BACKEND_LOG"
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    err "Frontend exited unexpectedly — check $FRONTEND_LOG"
fi

cleanup
