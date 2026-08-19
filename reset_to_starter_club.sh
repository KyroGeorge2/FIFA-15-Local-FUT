#!/usr/bin/env bash
# FIFA 15 Local FUT - reset to the fresh public-test starter club (Linux)
# WARNING: deletes your LOCAL FUT club/save. Does not touch normal FIFA 15
# Career/Settings saves.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/FIFA15LocalFUT"
CONFIG_FILE="$CONFIG_DIR/config.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FIFA15LocalFUT"

say() { printf '\033[1;34m[LocalFUT]\033[0m %s\n' "$*"; }

echo "============================================================"
echo " RESET FIFA 15 LOCAL FUT TO PUBLIC-TEST STARTER CLUB"
echo "============================================================"
echo "  WARNING: This deletes your LOCAL FUT club/save."
echo "  It does not touch normal FIFA 15 Career/Settings saves."
echo

read -r -p "Type RESET to continue: " OK
[ "$OK" = "RESET" ] || { echo "Cancelled."; exit 0; }

# Stop the server first so it cannot write while we delete
"$SCRIPT_DIR/stop.sh"

rm -f \
  "$STATE_DIR/fut15-local.sqlite3" \
  "$STATE_DIR/fut15-local.sqlite3-wal" \
  "$STATE_DIR/fut15-local.sqlite3-shm" \
  "$STATE_DIR/data/localfut15.sqlite3" \
  "$STATE_DIR/data/localfut15.sqlite3-wal" \
  "$STATE_DIR/data/localfut15.sqlite3-shm"

echo
echo "Reset complete. The next Local FUT launch will create the barebones"
echo "bronze starter club from this public-test build."
