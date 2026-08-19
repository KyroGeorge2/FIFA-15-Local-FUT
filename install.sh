#!/usr/bin/env bash
# FIFA 15 Local FUT - Linux installer (public test)
#
# Finds the FIFA 15 installation (Lutris prefix or a folder you provide),
# backs up the files it replaces, installs the Local FUT payload into the
# game folder, sets the Wine dinput8 override, and writes a config file the
# other scripts read.
#
# Run this once, then use play.sh to launch.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD="$SCRIPT_DIR/payload"
STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/FIFA15LocalFUT"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/FIFA15LocalFUT"
CONFIG_FILE="$CONFIG_DIR/config.sh"
BACKUP_DIR="$STATE_DIR/install-backup"

# The files the mod replaces/installs next to fifa15.exe. The .big/.bh
# archives are intentionally NOT listed here: this repo checks them in via
# git-lfs, so a plain checkout only has pointer files. The installer skips
# LFS pointers and keeps the real archives already present in the game
# folder (same CPY-era lineage the mod is built on).
PAYLOAD_COPY=(
  dinput8.dll
  CardsDLLzf.dll
  ItsAMe_Origin.dll
  EA-MITM.ini
  cl.ini
)
DLC_COPY=(
  CardsDLLzf.dll
)

say()  { printf '\033[1;34m[LocalFUT]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[LocalFUT]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[LocalFUT]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Prerequisites: python3 + cryptography
# ---------------------------------------------------------------------------
check_python() {
  command -v python3 >/dev/null 2>&1 || die "python3 not found. Install it: sudo dnf install python3"
  if ! python3 -c 'import cryptography' >/dev/null 2>&1; then
    say "Installing the required Python package: cryptography"
    python3 -m pip install --user --break-system-packages --disable-pip-version-check cryptography \
      || die "Could not install cryptography. Try: sudo dnf install python3-cryptography"
  fi
  python3 -c 'import sqlite3, cryptography; print("Python", __import__("sys").version.split()[0], "| SQLite", sqlite3.sqlite_version, "| cryptography", cryptography.__version__)'
}

# ---------------------------------------------------------------------------
# 2. Locate game folder + Wine prefix
# ---------------------------------------------------------------------------
find_from_lutris() {
  # Look for a Lutris game whose executable is fifa15.exe
  local yml
  for yml in "$HOME"/.local/share/lutris/games/*.yml; do
    [ -f "$yml" ] || continue
    local exe prefix
    exe="$(sed -n 's/^  exe: //p' "$yml" | head -1)"
    prefix="$(sed -n 's/^  prefix: //p' "$yml" | head -1)"
    if [ -n "$exe" ] && [ -f "$exe" ]; then
      local exe_name
      exe_name="$(basename "$exe")"
      if [ "$exe_name" = "fifa15.exe" ]; then
        GAME_DIR="$(dirname "$exe")"
        WINEPREFIX="$prefix"
        return 0
      fi
    fi
  done
  return 1
}

locate_game() {
  if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONFIG_FILE"
    [ -f "$GAME_DIR/fifa15.exe" ] && return 0
  fi
  if find_from_lutris; then
    say "Found FIFA 15 via Lutris: $GAME_DIR (prefix $WINEPREFIX)"
    return 0
  fi
  if [ -d "$HOME/Games/FIFA 15" ] && [ -f "$HOME/Games/FIFA 15/fifa15.exe" ]; then
    GAME_DIR="$HOME/Games/FIFA 15"
    WINEPREFIX="${WINEPREFIX:-$HOME/Games/Prefix/FIFA15}"
    return 0
  fi
  warn "Could not find FIFA 15 automatically."
  read -r -p "Enter the folder containing fifa15.exe: " GAME_DIR
  [ -f "$GAME_DIR/fifa15.exe" ] || die "fifa15.exe not found in $GAME_DIR"
  read -r -p "Enter the Wine prefix for this game (or leave blank): " WINEPREFIX
  return 0
}

find_proton() {
  # Newest GE-Proton/Wine-GE compatibility tool, like Lutris picks by default
  local d newest=""
  for d in "$HOME"/.local/share/Steam/compatibilitytools.d/GE-Proton*; do
    [ -d "$d" ] && newest="$d"
  done
  PROTONPATH="${PROTONPATH:-$newest}"
  [ -n "$PROTONPATH" ] && [ -d "$PROTONPATH" ] || {
    warn "GE-Proton not found under ~/.local/share/Steam/compatibilitytools.d/"
    read -r -p "Enter the path to your GE-Proton directory (or leave blank to skip): " PROTONPATH
  }
}

# ---------------------------------------------------------------------------
# 3. Install payload
# ---------------------------------------------------------------------------
is_lfs_pointer() {
  # git-lfs pointer files are tiny text stubs ("version https://git-lfs...").
  # Never copy those over a real game archive.
  [ "$(stat -c %s "$1" 2>/dev/null || echo 0)" -lt 200 ] && head -c 40 "$1" 2>/dev/null | grep -q "git-lfs"
}

install_payload() {
  mkdir -p "$BACKUP_DIR"
  local f target
  for f in "${PAYLOAD_COPY[@]}"; do
    [ -f "$PAYLOAD/$f" ] || { warn "payload/$f missing, skipping"; continue; }
    is_lfs_pointer "$PAYLOAD/$f" && { warn "payload/$f is a git-lfs pointer (no real file in this checkout), skipping"; continue; }
    if [ -f "$GAME_DIR/$f" ] && [ ! -f "$BACKUP_DIR/$f" ]; then
      cp -p "$GAME_DIR/$f" "$BACKUP_DIR/$f"
    fi
    cp -f "$PAYLOAD/$f" "$GAME_DIR/$f"
    say "installed $f"
  done

  # dlc/dlc_CardsDLL/dlc/CardsDLLzf.dll
  target="$GAME_DIR/dlc/dlc_CardsDLL/dlc"
  mkdir -p "$target"
  if [ -f "$target/CardsDLLzf.dll" ] && [ ! -f "$BACKUP_DIR/dlc_CardsDLL" ]; then
    mkdir -p "$BACKUP_DIR/dlc_CardsDLL"
    cp -p "$target/CardsDLLzf.dll" "$BACKUP_DIR/dlc_CardsDLL/CardsDLLzf.dll"
  fi
  for f in "${DLC_COPY[@]}"; do
    [ -f "$PAYLOAD/$f" ] || continue
    is_lfs_pointer "$PAYLOAD/$f" && continue
    cp -f "$PAYLOAD/$f" "$target/$f"
  done
  say "installed dlc/dlc_CardsDLL/dlc/CardsDLLzf.dll"

  # Copy the whole localfut15/ server package (server.py, catalogs, config).
  # The server resolves its game folder as the parent of its own directory,
  # so it must live inside the game folder (mirrors the Windows installer's
  # xcopy). Skip any git-lfs pointer files.
  if [ -d "$PAYLOAD/localfut15" ]; then
    mkdir -p "$GAME_DIR/localfut15"
    (
      cd "$PAYLOAD/localfut15"
      find . -type f | while read -r f; do
        if is_lfs_pointer "$f"; then
          warn "payload/localfut15/$f is a git-lfs pointer, skipping"
          continue
        fi
        mkdir -p "$GAME_DIR/localfut15/$(dirname "$f")"
        cp -f "$f" "$GAME_DIR/localfut15/$f"
      done
    )
    say "installed localfut15/ server package"
  fi
}

# ---------------------------------------------------------------------------
# 4. Wine dinput8 override (native proxy must load instead of Wine's builtin)
# ---------------------------------------------------------------------------
set_dinput8_override() {
  [ -n "${WINEPREFIX:-}" ] || return 0
  [ -f "$WINEPREFIX/user.reg" ] || return 0
  local section='[Software\\Wine\\AppDefaults\\fifa15.exe\\DllOverrides]'
  if grep -Fq "$section" "$WINEPREFIX/user.reg"; then
    # Section exists: make sure the dinput8 line is present
    if ! grep -Fq '"dinput8"="native,builtin"' "$WINEPREFIX/user.reg"; then
      sed -i "/$(printf '%s' "$section" | sed 's/\\/\\\\/g')/a \\\"dinput8\"=\"native,builtin\"" "$WINEPREFIX/user.reg"
    fi
  else
    printf '\n%s 1786437965\n#time=1dd296dd8f09044\n"dinput8"="native,builtin"\n' "$section" >> "$WINEPREFIX/user.reg"
  fi
  say "dinput8 -> native,builtin override set for fifa15.exe"
}

# ---------------------------------------------------------------------------
# 5. Write config
# ---------------------------------------------------------------------------
write_config() {
  mkdir -p "$CONFIG_DIR"
  cat > "$CONFIG_FILE" <<EOF
# FIFA 15 Local FUT - Linux config (generated by install.sh)
GAME_DIR="$GAME_DIR"
WINEPREFIX="$WINEPREFIX"
PROTONPATH="$PROTONPATH"
GAMEID="umu-default"
STATE_DIR="$STATE_DIR"
EOF
  say "config written to $CONFIG_FILE"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
say "============================================================"
say " FIFA 15 LOCAL FUT - LINUX INSTALLER"
say "============================================================"
check_python
locate_game
find_proton
install_payload
set_dinput8_override
write_config

say "Install/update complete: $GAME_DIR"
say "Next: run ./play.sh to start the server and launch FIFA 15."
