#!/usr/bin/env bash
# FIFA 15 Local FUT - Linux launcher
#
# Starts the localhost FUT server (if not already running) and launches
# FIFA 15 through the same Wine/Proton stack Lutris uses (umu-run), with the
# Local FUT redirect chain active.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/FIFA15LocalFUT"
CONFIG_FILE="$CONFIG_DIR/config.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FIFA15LocalFUT"

say()  { printf '\033[1;34m[LocalFUT]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[LocalFUT]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

if [ ! -f "$CONFIG_FILE" ]; then
  die "No config found. Run ./install.sh first."
fi
# shellcheck disable=SC1090
. "$CONFIG_FILE"

[ -f "$GAME_DIR/fifa15.exe" ] || die "fifa15.exe not found at $GAME_DIR"
command -v python3 >/dev/null 2>&1 || die "python3 not found"

# ---------------------------------------------------------------------------
# 1. Server: start if not already running
# ---------------------------------------------------------------------------
SERVER_PY="$GAME_DIR/localfut15/server.py"
[ -f "$SERVER_PY" ] || die "Server package missing at $SERVER_PY (run ./install.sh again)"

start_server() {
  mkdir -p "$STATE_DIR/logs"
  # LOCALAPPDATA must be the *parent* of FIFA15LocalFUT: the server and the
  # coin tool append "FIFA15LocalFUT" to it (Windows semantics).
  local appdata="${XDG_DATA_HOME:-$HOME/.local/share}"
  LOCALAPPDATA="$appdata" nohup python3 "$SERVER_PY" --host 127.0.0.1 \
    > "$STATE_DIR/logs/server-console.log" 2>&1 &
  say "Server starting (pid $!)..."
  local i port
  for i in $(seq 1 40); do
    sleep 1
    if grep -q "All localhost services ready" "$STATE_DIR/logs/server-console.log" 2>/dev/null; then
      say "Server ready."
      return 0
    fi
    if ! kill -0 "$!" 2>/dev/null; then
      die "Server exited during startup. Last log lines:"
      tail -20 "$STATE_DIR/logs/server-console.log" >&2
    fi
  done
  die "Server did not become ready in time. See $STATE_DIR/logs/server-console.log"
}

if pgrep -f "server.py --host 127.0.0.1" >/dev/null 2>&1; then
  say "Server already running."
else
  start_server
fi

# ---------------------------------------------------------------------------
# 2. Launch the game
# ---------------------------------------------------------------------------
UMU_RUN="${UMU_RUN:-$HOME/.local/share/lutris/runtime/umu/umu-run}"
if [ ! -x "$UMU_RUN" ]; then
  UMU_RUN="$(command -v umu-run 2>/dev/null || true)"
fi
[ -n "$UMU_RUN" ] || die "umu-run not found. Is Lutris installed?"

if [ -z "${PROTONPATH:-}" ] || [ ! -d "${PROTONPATH:-}" ]; then
  warn "PROTONPATH not set/valid; umu-run will use its default Proton build."
fi

say "Launching FIFA 15 (${GAME_DIR}/fifa15.exe)..."
mkdir -p "$STATE_DIR/logs"
(
  cd "$GAME_DIR"
  PROTONPATH="$PROTONPATH" \
  GAMEID="${GAMEID:-umu-default}" \
  WINEPREFIX="$WINEPREFIX" \
  LOCALAPPDATA="${XDG_DATA_HOME:-$HOME/.local/share}" \
    "$UMU_RUN" "$GAME_DIR/fifa15.exe"
) > "$STATE_DIR/logs/game-launch.log" 2>&1 &
say "Game launched. Logs: $STATE_DIR/logs/game-launch.log"
say "FUT server log: $STATE_DIR/logs/server-console.log"
