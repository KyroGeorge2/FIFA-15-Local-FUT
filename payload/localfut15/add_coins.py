from __future__ import annotations
import json
import os
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: add_coins.py <amount>")
        return 2
    try:
        amount = int(sys.argv[1].replace(",", "").strip())
    except ValueError:
        print("ERROR: Coin amount must be a whole number.")
        return 2
    if amount <= 0:
        print("ERROR: Coin amount must be greater than zero.")
        return 2
    if amount > 100_000_000:
        print("ERROR: For safety, add at most 100,000,000 coins at a time.")
        return 2

    local = os.environ.get("LOCALAPPDATA")
    if not local:
        print("ERROR: LOCALAPPDATA is unavailable.")
        return 3
    root = Path(local) / "FIFA15LocalFUT"
    root.mkdir(parents=True, exist_ok=True)
    db = root / "fut15-local.sqlite3"

    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = con.execute("SELECT value FROM kv WHERE key='credits'").fetchone()
        current = int(json.loads(row[0])) if row else 0
        new_total = current + amount
        con.execute(
            "INSERT INTO kv(key,value) VALUES('credits',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(new_total),),
        )
        con.commit()
    finally:
        con.close()
    print(f"Coins added: {amount:,}")
    print(f"New balance: {new_total:,}")
    print("If FIFA/FUT is open, leave FUT and re-enter (or restart Local FUT) to refresh the balance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
