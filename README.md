# FIFA 15 Local FUT

Local/offline FIFA 15 Ultimate Team restoration build for PC, based on the working v0.2.39 backend. Runs on **Windows** (original) and **Linux** (Wine/Proton via Lutris).

The project is intended for local/offline restoration testing. It requires your own installed copy of FIFA 15 PC and does not connect you to EA's retired FUT service.

---

## Windows quick start

1. Extract the ZIP to a normal folder (for example, Downloads).
2. Run **`INSTALL_PREREQUISITES.cmd`** once. It checks/installs Python, the required Python package, and the Visual C++ runtime used by the FIFA 15 Cards DLL.
3. Run **`PLAY_LOCAL_FUT15.cmd`**. On first run it finds your FIFA 15 installation, backs up files it replaces, installs the Local FUT payload, creates a desktop shortcut, starts the localhost services, and launches FIFA 15.
4. Future launches can use the **FIFA 15 Local FUT** desktop shortcut.

## Linux quick start (Wine/Proton)

The Linux scripts assume FIFA 15 is installed in a Wine prefix managed by [Lutris](https://lutris.net/) (the standard way to run Origin-era games on Linux). Any recent GE-Proton/Proton build works; the installer will detect yours automatically.

1. **One-time dependency setup.** The scripts need Python 3.10+ with the `cryptography` package. On Fedora:

   ```bash
   sudo dnf install python3
   python3 -m pip install --user --break-system-packages cryptography
   ```

   (On other distros, install `python3` and `cryptography` through your package manager.)

2. **Install.** From this repo folder:

   ```bash
   ./install.sh
   ```

   It locates your FIFA 15 folder (via Lutris or by asking), backs up every file it replaces, installs the Local FUT payload into the game folder, sets the Wine `dinput8` override the hook chain needs, and writes a small config under `~/.config/FIFA15LocalFUT/`.

3. **Play.**

   ```bash
   ./play.sh
   ```

   This starts the localhost FUT server (if it isn't already running) and launches FIFA 15 through the same Proton stack Lutris uses. Everything runs on `127.0.0.1` only — no internet access is involved.

> **Note:** the repo stores some `.big` content archives with git-lfs, so a plain clone only contains pointer stubs for them. The installer detects these and deliberately leaves your game's existing archives untouched — they come from the same code line the mod is built on.

### Linux helper scripts

| Script | Purpose |
|---|---|
| `install.sh` | First-run installer: locate game, back up, install payload, set Wine override, write config |
| `play.sh` | Start the server (if needed) and launch FIFA 15 |
| `stop.sh` | Stop the server and game |
| `status.sh` | Show which localhost services are up and the game's state |
| `add_coins.sh [amount]` | Add local coins (default 1,000,000) |
| `reset_to_starter_club.sh` | Delete the Local FUT database only (requires typing `RESET`) |
| `restore_backup.sh` | Restore the game files backed up by `install.sh` |

### Linux state and logs

Runtime state lives in `~/.local/share/FIFA15LocalFUT/` (the XDG equivalent of `%LOCALAPPDATA%`):

- `fut15-local.sqlite3` — the local club save (coins, squads, items, transfer list)
- `logs/` — verbose server and game logs, useful when reporting bugs
- `install-backup/` — the game files `install.sh` replaced

## Fresh starter club

A brand-new Local FUT save starts intentionally small:

- **0 coins** by default.
- **14 bronze Premier League players** only (including a usable mix of GK/DEF/MID/ST positions).
- One active **Arsenal badge**.
- **Arsenal home + away kits**.
- One starter **stadium** (Sanderson Park).
- One starter **ball** so matches have a complete club identity.
- One starter squad, with additional squads supported.

FUT will still let you choose/confirm your own club name. Club progress, coins, squads, items and Transfer List state are persisted in `fut15-local.sqlite3` (see paths above).

If you want to test the exact fresh-public state again, run **`RESET_TO_STARTER_CLUB.cmd`** (Windows) or **`reset_to_starter_club.sh`** (Linux). These only delete the Local FUT database; they do not touch normal Career/Settings saves.

## Optional test coins

Run **`ADD_COINS.cmd`** (Windows) or **`add_coins.sh`** (Linux) and enter how many local coins you want to add. The default is 1,000,000 coins. This modifies only the localhost FUT SQLite balance.

## What is included

- Persistent local FUT club/profile.
- Store and pack opening, including promo packs.
- FIFA 15 player database and special-card pack pools.
- Club consumables.
- Badge/kit/stadium/ball support.
- Transfer List lifecycle, relisting, sold-item clearing and quick sell.
- Large deterministic local AI Transfer Market and local AI buyers for user listings.
- Multiple squads.
- Offline Seasons work from the current development line.
- Port auto-remapping for local FIFA services where possible.

This is a **test build**, so logs are intentionally verbose. On Windows they live under `%LOCALAPPDATA%\FIFA15LocalFUT\logs`; on Linux under `~/.local/share/FIFA15LocalFUT/logs`.

## Files testers should care about

Windows:

- `INSTALL_PREREQUISITES.cmd` — one-time dependency setup.
- `PLAY_LOCAL_FUT15.cmd` — main first-run installer/launcher.
- `ADD_COINS.cmd` — optional local coin helper.
- `RESET_TO_STARTER_CLUB.cmd` — optional destructive Local FUT reset.
- `RESTORE_BACKUP.cmd` — restores game files backed up by the Local FUT installer.

Linux:

- `install.sh` / `play.sh` / `stop.sh` / `status.sh` — install, launch, stop, check.
- `add_coins.sh` / `reset_to_starter_club.sh` / `restore_backup.sh` — the same helpers, ported.

Everything inside `payload/` is installed automatically by the launcher (both platforms).

## About `ItsAMe_Origin.dll`

The filename is intentionally left unchanged. It is part of the compatibility chain used by this build and its exact filename is embedded in the binary, so renaming it just for presentation could break startup on clean machines.

## Linux troubleshooting

- **Game freezes after the language select screen.** This is the classic symptom of the Origin session handshake never completing. Make sure `install.sh` ran (so the `dinput8.dll` proxy, `EA-MITM.ini` and `cl.ini` are in the game folder) and that `play.sh` reports the server ready before you launch. `status.sh` should show all seven services listening on `127.0.0.1`.
- **`dinput8` override missing.** `install.sh` writes a `dinput8=native,builtin` override for `fifa15.exe` in the prefix registry (`user.reg`). If you recreated the prefix, run `install.sh` again.
- **Server won't start.** Check `~/.local/share/FIFA15LocalFUT/logs/server-console.log`. The server needs the `cryptography` Python package.
- **Port conflicts.** The server picks fallback ports automatically when a service port is taken, and writes the final map to `runtime_ports.json` in the state folder.

## Bug reports

When reporting a problem, include:

- What screen/action you were on.
- What you expected to happen.
- What actually happened/crashed/froze.
- The newest log from the state folder (`%LOCALAPPDATA%\FIFA15LocalFUT\logs` on Windows, `~/.local/share/FIFA15LocalFUT/logs` on Linux).

Please test on a legitimate FIFA 15 PC installation and keep reports focused on the localhost/offline restoration.
