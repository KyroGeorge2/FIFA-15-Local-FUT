# FIFA 15 Local FUT — Public Test 1

Local/offline FIFA 15 Ultimate Team restoration test build for PC, based on the working v0.2.39 backend.

## Quick start

1. Extract the ZIP to a normal folder (for example, Downloads).
2. Run **`INSTALL_PREREQUISITES.cmd`** once. It checks/installs Python, the required Python package, and the Visual C++ runtime used by the FIFA 15 Cards DLL.
3. Run **`PLAY_LOCAL_FUT15.cmd`**. On first run it finds your FIFA 15 installation, backs up files it replaces, installs the Local FUT payload, creates a desktop shortcut, starts the localhost services, and launches FIFA 15.
4. Future launches can use the **FIFA 15 Local FUT** desktop shortcut.

This requires your own installed copy of FIFA 15 PC. The project is intended for local/offline restoration testing; it does not connect you to EA's retired FUT service.

## Fresh starter club

A brand-new Local FUT save starts intentionally small:

- **0 coins** by default.
- **14 bronze Premier League players** only (including a usable mix of GK/DEF/MID/ST positions).
- One active **Arsenal badge**.
- **Arsenal home + away kits**.
- One starter **stadium** (Sanderson Park).
- One starter **ball** so matches have a complete club identity.
- One starter squad, with additional squads supported.

FUT will still let the player choose/confirm their own club name. Club progress, coins, squads, items and Transfer List state are persisted in:

`%LOCALAPPDATA%\FIFA15LocalFUT\fut15-local.sqlite3`

If you previously used a development build and want to test the exact fresh-public state, run **`RESET_TO_STARTER_CLUB.cmd`**. It only deletes the Local FUT database; it does not delete normal Career/Settings saves.

## Optional test coins

Run **`ADD_COINS.cmd`** and enter how many local coins you want to add. The default is 1,000,000 coins. This modifies only the localhost FUT SQLite balance.

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

This is a **test release**, so logs are intentionally verbose. They are stored under `%LOCALAPPDATA%\FIFA15LocalFUT\logs` and are useful when reporting bugs.

## If FIFA does not launch

The launcher waits for the localhost FUT service before starting FIFA 15 and,
if it gives up, now prints the specific reason instead of a generic timeout:

- **Still installing Python dependencies** — run `INSTALL_PREREQUISITES.cmd`
  once, let it finish, then launch again.
- **Server process exited during startup** — the Local FUT Server window names
  the failing service and port. Read it before closing it.
- **Different Windows profile** — launch with "Run as administrator" from an
  account that is itself an administrator, rather than typing another account's
  credentials at the UAC prompt.
- **Port refuses connections** — a security suite is intercepting loopback. Run
  `PORT_DIAGNOSTICS.cmd` and `LOCAL_FUT_STATUS.cmd`.

A cold first start has to seed the local card database and can take a while on
slow disks. The default wait is 180 seconds; raise it if needed by running
`set LOCALFUT_WAIT_SECONDS=300` in the same window before the launcher.

## Files new testers should care about

- `INSTALL_PREREQUISITES.cmd` — one-time dependency setup.
- `PLAY_LOCAL_FUT15.cmd` — main first-run installer/launcher.
- `ADD_COINS.cmd` — optional local coin helper.
- `RESET_TO_STARTER_CLUB.cmd` — optional destructive Local FUT reset.
- `RESTORE_BACKUP.cmd` — restores game files backed up by the Local FUT installer.

Everything inside `payload/` is installed automatically by the main launcher.

## About `ItsAMe_Origin.dll`

The filename is intentionally left unchanged. It is part of the compatibility chain used by this build and its exact filename is embedded in the binary, so renaming it just for presentation could break startup on clean machines.

## Bug reports

When reporting a problem, include:

- What screen/action you were on.
- What you expected to happen.
- What actually happened/crashed/froze.
- The newest log from `%LOCALAPPDATA%\FIFA15LocalFUT\logs`.

Please test on a legitimate FIFA 15 PC installation and keep reports focused on the localhost/offline restoration.
