#!/usr/bin/env bash
# FIFA 15 Local FUT - service status
set -u

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/FIFA15LocalFUT"
CONFIG_FILE="$CONFIG_DIR/config.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FIFA15LocalFUT"
[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"

PORTS=(3216 42230 10051 17502 42232 8199 8099)

echo "============================================================"
echo " FIFA 15 LOCAL FUT - SERVICE STATUS"
echo "============================================================"

if pgrep -f "server.py --host 127.0.0.1" >/dev/null 2>&1; then
  echo "Server process: RUNNING (pid $(pgrep -f 'server.py --host 127.0.0.1' | head -1))"
else
  echo "Server process: NOT RUNNING"
fi

for p in "${PORTS[@]}"; do
  line="$(ss -tlnp 2>/dev/null | grep -F ":$p " | head -1)"
  if [ -n "$line" ]; then
    pid="$(echo "$line" | grep -oP 'pid=\K[0-9]+' | head -1)"
    name="$(echo "$line" | grep -oP 'users:\(\("\K[^"]+' | head -1)"
    echo "OK    127.0.0.1:$p  PID ${pid:-?}  ${name:-?}"
  else
    echo "MISS  127.0.0.1:$p"
  fi
done

if [ -n "${GAME_DIR:-}" ] && pgrep -f "$GAME_DIR/fifa15.exe" >/dev/null 2>&1; then
  echo "Game: RUNNING (pid $(pgrep -f "$GAME_DIR/fifa15.exe" | head -1))"
else
  echo "Game: not running"
fi

echo "State dir: $STATE_DIR"
echo "Logs:      $STATE_DIR/logs"
