#!/usr/bin/env bash
# FIFA 15 Local FUT - optional local coin tool (Linux)
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/FIFA15LocalFUT"
CONFIG_FILE="$CONFIG_DIR/config.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FIFA15LocalFUT"

say() { printf '\033[1;34m[LocalFUT]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[LocalFUT]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

echo "============================================================"
echo " FIFA 15 LOCAL FUT - OPTIONAL COIN TOOL"
echo "============================================================"
echo "  This changes only your LOCAL offline FUT balance."
echo

[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"

ADD_COINS="$GAME_DIR/localfut15/add_coins.py"
[ -f "$ADD_COINS" ] || ADD_COINS="$SCRIPT_DIR/payload/localfut15/add_coins.py"
[ -f "$ADD_COINS" ] || die "add_coins.py not found. Run ./install.sh first."

AMOUNT="${1:-}"
if [ -z "$AMOUNT" ]; then
  read -r -p "Coins to add [default 1000000]: " AMOUNT
fi
AMOUNT="${AMOUNT:-1000000}"

# LOCALAPPDATA must be the parent of FIFA15LocalFUT (Windows semantics):
# add_coins.py appends "FIFA15LocalFUT" to it.
LOCALAPPDATA="${XDG_DATA_HOME:-$HOME/.local/share}" python3 "$ADD_COINS" "$AMOUNT" || exit $?
echo
