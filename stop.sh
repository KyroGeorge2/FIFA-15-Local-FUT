#!/usr/bin/env bash
# FIFA 15 Local FUT - stop server and game
set -u

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/FIFA15LocalFUT"
CONFIG_FILE="$CONFIG_DIR/config.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FIFA15LocalFUT"

say() { printf '\033[1;34m[LocalFUT]\033[0m %s\n' "$*"; }

[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"

# Stop the localhost server (the FUT server runs as "server.py --host 127.0.0.1")
pkill -f "server.py --host 127.0.0.1" 2>/dev/null && say "Server stopped." || say "Server was not running."

# Stop the game itself
pkill -f "$GAME_DIR/fifa15.exe" 2>/dev/null && say "Game stopped."

# Stop the wineserver that belongs to this prefix (match via its environment)
if [ -n "${WINEPREFIX:-}" ]; then
  for pid in $(pgrep -x wineserver 2>/dev/null); do
    if tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -q "^WINEPREFIX=$WINEPREFIX$"; then
      kill "$pid" 2>/dev/null && say "Wineserver stopped (pid $pid)."
    fi
  done
fi

rm -f "$STATE_DIR/runtime_ports.json"
say "Done."
