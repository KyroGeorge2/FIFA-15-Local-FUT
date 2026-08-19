#!/usr/bin/env bash
# FIFA 15 Local FUT - restore the game files backed up by install.sh (Linux)
set -u

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/FIFA15LocalFUT"
CONFIG_FILE="$CONFIG_DIR/config.sh"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FIFA15LocalFUT"

say() { printf '\033[1;34m[LocalFUT]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[LocalFUT]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"
BACKUP_DIR="$STATE_DIR/install-backup"

[ -d "$BACKUP_DIR" ] || die "No installer backup found at $BACKUP_DIR"
[ -n "${GAME_DIR:-}" ] && [ -d "$GAME_DIR" ] || die "GAME_DIR not configured. Run ./install.sh first."

cp -f "$BACKUP_DIR"/* "$GAME_DIR"/ 2>/dev/null && say "Restored game folder files."

if [ -f "$BACKUP_DIR/dlc_CardsDLL/CardsDLLzf.dll" ] && [ -d "$GAME_DIR/dlc/dlc_CardsDLL/dlc" ]; then
  cp -f "$BACKUP_DIR/dlc_CardsDLL/CardsDLLzf.dll" "$GAME_DIR/dlc/dlc_CardsDLL/dlc/CardsDLLzf.dll"
  say "Restored dlc/dlc_CardsDLL/dlc/CardsDLLzf.dll."
fi

say "Backup restored. Run ./install.sh again to re-apply Local FUT."
