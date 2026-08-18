from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import os
import random
import re
import secrets
import html
import socket
import socketserver
import sqlite3
import struct
import threading
import time
import traceback
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except Exception as _crypto_import_error:
    padding = Cipher = algorithms = modes = None
else:
    _crypto_import_error = None

APP_NAME = "FIFA15 Local FUT"
VERSION = "0.2.43-current-season-reset-fix"
ROOT = Path(__file__).resolve().parent
# Keep runtime state outside the FIFA installation directory. FIFA is commonly
# installed under Program Files, where a normal user cannot create SQLite/log
# files. Configuration remains beside server.py, while mutable state goes to
# %%LOCALAPPDATA%%\FIFA15LocalFUT.
_local_app_data = os.environ.get("LOCALAPPDATA")
if _local_app_data:
    RUNTIME_ROOT = Path(_local_app_data) / "FIFA15LocalFUT"
else:
    RUNTIME_ROOT = Path.home() / "AppData" / "Local" / "FIFA15LocalFUT"
DATA = RUNTIME_ROOT / "data"
LOGS = RUNTIME_ROOT / "logs"
# v0.2.29 promotes the SQLite save to the LocalAppData profile root so every
# future build shares one obvious, version-independent club database.  Older
# builds stored the same database one level deeper under data\.
LEGACY_DB_PATH = DATA / "localfut15.sqlite3"
DB_PATH = RUNTIME_ROOT / "fut15-local.sqlite3"
CONFIG_PATH = ROOT / "config.json"

DATA.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    defaults = {
        "display_name": "LocalPlayer",
        "nucleus_id": 1000000001,
        "persona_id": 1000000002,
        "club_id": 1,
        "club_name": "Local FC",
        "club_abbr": "LCL",
        "credits": 500000,
        "fut_game": "fifa15",
        "game_sku": "FFA15PCC",
        "fut_sku": "FUT15PCC",
        "redirect_port": 42230,
        "blaze_port": 10051,
        "qos_port": 17502,
        "easw_port": 42232,
        "fut_port": 8199,
        "legacy_fut_port": 8099,
        "lsx_port": 3216,
        "starter_players": [20801, 158023, 190871, 176580, 173731, 188545, 153079, 183277, 167495, 155862, 164240, 177003, 182521, 195864],
        "pack_size": 12,
        "pack_cost": 7500,
        "special_pack_chance": 0.10,
        "rare_flag": 1,
        "debug_unknown_http": True,
        "ai_market_enabled": True,
        "ai_market_fast_sales_seconds": 20,
        "ai_market_results": 0,  # legacy: 0 means use the full FIFA 15 card database
        "ai_market_copies_per_card": 10,
        "offline_seasons_enabled": True,
        "starter_cosmetics_only": False,
    }
    if CONFIG_PATH.exists():
        try:
            supplied = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(supplied, dict):
                defaults.update(supplied)
        except Exception:
            pass

    # 0.1.9.1: network topology is protocol compatibility data, not a user
    # preference.  The original 0.1 package wrote blaze_port=17502 and
    # fut_port=8099 into config.json; leaving that file in place silently
    # overrode the V3-captured topology introduced in 0.1.9.  Force these
    # ports after loading config so stale installs cannot regress routing.
    defaults.update({
        "redirect_port": 42230,
        "blaze_port": 10051,
        "qos_port": 17502,
        "easw_port": 42232,
        "fut_port": 8199,
        "legacy_fut_port": 8099,
        "lsx_port": 3216,
    })
    return defaults

CFG = load_config()

PACK_SETTINGS_PATH = ROOT / "pack_settings.json"

DEFAULT_SPECIAL_WEIGHTS = {"3":55,"4":4,"5":2,"6":3,"7":4,"8":12,"9":5,"11":8}
DEFAULT_PACK_SETTINGS = {
    "next_pack_id": 20,
    "packs": {
        "1": {"enabled": True, "category":"bronze", "name":"Bronze Pack", "bio":"A mix of 12 items, including players, club items and consumables, at least 10 Bronze with 1 rare.", "price":400, "fifa_points":0, "size":12, "player_slots":3, "club_item_slots":2, "gold_weight":0, "silver_weight":5, "bronze_weight":95, "rare_slots":1, "player_rare_slots":1, "special_chance":0.0, "special_weights":dict(DEFAULT_SPECIAL_WEIGHTS)},
        "2": {"enabled": True, "category":"bronze", "name":"Premium Bronze Pack", "bio":"A mix of 12 items, including players, club items and consumables, at least 10 Bronze with 3 rare.", "price":750, "fifa_points":0, "size":12, "player_slots":3, "club_item_slots":2, "gold_weight":0, "silver_weight":5, "bronze_weight":95, "rare_slots":3, "player_rare_slots":1, "special_chance":0.0, "special_weights":dict(DEFAULT_SPECIAL_WEIGHTS)},
        "3": {"enabled": True, "category":"silver", "name":"Silver Pack", "bio":"A mix of 12 items, including players, club items and consumables, at least 10 Silver with 1 rare.", "price":2500, "fifa_points":50, "size":12, "player_slots":3, "club_item_slots":2, "gold_weight":5, "silver_weight":95, "bronze_weight":0, "rare_slots":1, "player_rare_slots":1, "special_chance":0.0, "special_weights":dict(DEFAULT_SPECIAL_WEIGHTS)},
        "4": {"enabled": True, "category":"silver", "name":"Premium Silver Pack", "bio":"A mix of 12 items, including players, club items and consumables, at least 10 Silver with 3 rare.", "price":3750, "fifa_points":75, "size":12, "player_slots":3, "club_item_slots":2, "gold_weight":5, "silver_weight":95, "bronze_weight":0, "rare_slots":3, "player_rare_slots":1, "special_chance":0.0, "special_weights":dict(DEFAULT_SPECIAL_WEIGHTS)},
        "5": {"enabled": True, "category":"gold", "name":"Gold Pack", "bio":"A mix of 12 items, including players, club items and consumables, at least 10 Gold with 1 rare.", "price":5000, "fifa_points":100, "size":12, "player_slots":3, "club_item_slots":2, "gold_weight":95, "silver_weight":5, "bronze_weight":0, "rare_slots":1, "player_rare_slots":1, "special_chance":0.02, "special_weights":dict(DEFAULT_SPECIAL_WEIGHTS)},
        "6": {"enabled": True, "category":"gold", "name":"Premium Gold Pack", "bio":"A mix of 12 items, including players, club items and consumables, at least 10 Gold with 3 rare.", "price":7500, "fifa_points":150, "size":12, "player_slots":3, "club_item_slots":2, "gold_weight":95, "silver_weight":5, "bronze_weight":0, "rare_slots":3, "player_rare_slots":1, "special_chance":0.04, "special_weights":dict(DEFAULT_SPECIAL_WEIGHTS)},
    },
}

def _merge_pack_settings(raw):
    out=json.loads(json.dumps(DEFAULT_PACK_SETTINGS))
    if not isinstance(raw,dict):
        return out

    # Compatibility with older local pack-settings files that stored one global
    # special_weights object. Use it only as a fallback for packs that do not
    # yet contain their own weights. Legends (12) and iMOTM (15) stay disabled.
    legacy_weights=raw.get("special_weights") if isinstance(raw.get("special_weights"),dict) else DEFAULT_SPECIAL_WEIGHTS
    legacy_weights={str(k):v for k,v in legacy_weights.items() if str(k) not in ("12","15")}

    if isinstance(raw.get("packs"),dict):
        out["packs"]={}
        for pid,cfg in raw["packs"].items():
            if isinstance(cfg,dict):
                base={"enabled":True,"name":f"FUT Pack {pid}","bio":"A FIFA 15 Ultimate Team pack.","price":7500,"size":12,
                      "gold_weight":100,"silver_weight":0,"bronze_weight":0,
                      "rare_slots":3,"special_chance":0.10,"special_weights":dict(legacy_weights)}
                base.update(cfg)
                weights=base.get("special_weights") if isinstance(base.get("special_weights"),dict) else legacy_weights
                weights={str(k):v for k,v in weights.items() if str(k) not in ("12","15")}
                for rf in DEFAULT_SPECIAL_WEIGHTS:
                    weights.setdefault(rf,0)
                base["special_weights"]=weights
                out["packs"][str(pid)]=base
    try:
        out["next_pack_id"]=int(raw.get("next_pack_id", max([int(x) for x in out["packs"]] or [3])+1))
    except Exception:
        out["next_pack_id"]=max([int(x) for x in out["packs"]] or [3])+1
    return out

def load_pack_settings():
    try:
        if PACK_SETTINGS_PATH.exists():
            return _merge_pack_settings(json.loads(PACK_SETTINGS_PATH.read_text(encoding="utf-8")))
    except Exception as exc:
        log.warning("Could not load pack_settings.json: %s", exc)
    return _merge_pack_settings({})

def get_pack_cfg(pack_id:int):
    settings=load_pack_settings()
    cfg=dict(settings.get("packs",{}).get(str(int(pack_id)),{}))
    cfg["_special_weights"]=dict(cfg.get("special_weights",{}))
    return cfg

# FIFA 15 base-card metadata for the starter pool.
# Face stats are [PAC, SHO, PAS, DRI, DEF, PHY] (GK: [DIV, HAN, KIC, REF, SPE, POS]).
PLAYER_DB = {
    20801:  {"name":"Cristiano Ronaldo","rating":92,"preferredPosition":"LW","leagueId":53,"teamid":243,"nation":38,"face":[93,93,81,91,32,79]},
    158023: {"name":"Lionel Messi","rating":93,"preferredPosition":"CF","leagueId":53,"teamid":241,"nation":52,"face":[93,89,86,96,27,62]},
    190871: {"name":"Neymar Jr","rating":86,"preferredPosition":"LW","leagueId":53,"teamid":241,"nation":54,"face":[90,80,72,92,30,58]},
    176580: {"name":"Luis Suarez","rating":89,"preferredPosition":"ST","leagueId":53,"teamid":241,"nation":60,"face":[83,87,79,88,42,79]},
    173731: {"name":"Gareth Bale","rating":87,"preferredPosition":"RM","leagueId":53,"teamid":243,"nation":50,"face":[94,83,83,84,63,81]},
    188545: {"name":"Robert Lewandowski","rating":87,"preferredPosition":"ST","leagueId":19,"teamid":21,"nation":37,"face":[81,84,74,85,39,78]},
    153079: {"name":"Sergio Aguero","rating":86,"preferredPosition":"ST","leagueId":13,"teamid":10,"nation":52,"face":[88,86,77,88,28,66]},
    183277: {"name":"Eden Hazard","rating":88,"preferredPosition":"LM","leagueId":13,"teamid":5,"nation":7,"face":[89,82,84,91,32,64]},
    167495: {"name":"Manuel Neuer","rating":90,"preferredPosition":"GK","leagueId":19,"teamid":21,"nation":21,"face":[87,85,92,86,58,90]},
    155862: {"name":"Sergio Ramos","rating":87,"preferredPosition":"CB","leagueId":53,"teamid":243,"nation":45,"face":[79,60,71,66,87,82]},
    164240: {"name":"Thiago Silva","rating":87,"preferredPosition":"CB","leagueId":16,"teamid":73,"nation":54,"face":[78,57,72,72,90,80]},
    177003: {"name":"Luka Modric","rating":87,"preferredPosition":"CM","leagueId":53,"teamid":243,"nation":10,"face":[76,74,85,89,71,70]},
    182521: {"name":"Toni Kroos","rating":85,"preferredPosition":"CM","leagueId":53,"teamid":243,"nation":21,"face":[58,81,89,84,58,69]},
    195864: {"name":"Paul Pogba","rating":83,"preferredPosition":"CM","leagueId":31,"teamid":45,"nation":18,"face":[76,78,79,83,73,88]},
}

# Optional external player database. This keeps the server logic small and lets
# the pack pool expand without hardcoding every player in this file.
PLAYER_DB_PATH = ROOT / "players.json"
if PLAYER_DB_PATH.exists():
    try:
        raw_player_db = json.loads(PLAYER_DB_PATH.read_text(encoding="utf-8"))
        if isinstance(raw_player_db, dict):
            for rid, meta in raw_player_db.items():
                if isinstance(meta, dict):
                    PLAYER_DB[int(rid)] = meta
        log_player_count = len(PLAYER_DB)
    except Exception:
        log_player_count = len(PLAYER_DB)
else:
    log_player_count = len(PLAYER_DB)

def player_meta(resource_id: int) -> dict[str, Any]:
    return PLAYER_DB.get(int(resource_id), {})

def player_attribute_list(resource_id: int) -> list[dict[str, int]]:
    face = player_meta(resource_id).get("face", [])
    return [{"index": i, "value": int(v)} for i, v in enumerate(face)]


# Mixed-pack consumables. The core category/subtype/resource families are the legacy FUT
# consumable identifiers used by the FIFA client. We keep a deliberately small, high-confidence
# subset for the first FIFA 15 PC mixed-pack pass: contracts, fitness, healing and training.
# More staff/club-item definitions can be added after the client confirms these render correctly.
CONSUMABLE_CATALOG: list[dict[str, Any]] = [
    # Player contracts
    {"resourceId":5001001,"cardassetid":7,"cardsubtypeid":201,"tier":"bronze","rating":50,"rareflag":0,"kind":"contract_player","bronze":8,"silver":2,"gold":1,"name":"Bronze Player Contract"},
    {"resourceId":5001004,"cardassetid":7,"cardsubtypeid":201,"tier":"bronze","rating":60,"rareflag":1,"kind":"contract_player","bronze":15,"silver":6,"gold":3,"name":"Rare Bronze Player Contract"},
    {"resourceId":5001002,"cardassetid":7,"cardsubtypeid":201,"tier":"silver","rating":65,"rareflag":0,"kind":"contract_player","bronze":10,"silver":10,"gold":8,"name":"Silver Player Contract"},
    {"resourceId":5001005,"cardassetid":7,"cardsubtypeid":201,"tier":"silver","rating":70,"rareflag":1,"kind":"contract_player","bronze":20,"silver":24,"gold":18,"name":"Rare Silver Player Contract"},
    {"resourceId":5001003,"cardassetid":7,"cardsubtypeid":201,"tier":"gold","rating":80,"rareflag":0,"kind":"contract_player","bronze":15,"silver":11,"gold":13,"name":"Gold Player Contract"},
    {"resourceId":5001006,"cardassetid":7,"cardsubtypeid":201,"tier":"gold","rating":90,"rareflag":1,"kind":"contract_player","bronze":28,"silver":24,"gold":28,"name":"Rare Gold Player Contract"},
    # Manager contracts
    {"resourceId":5001007,"cardassetid":8,"cardsubtypeid":202,"tier":"bronze","rating":50,"rareflag":0,"kind":"contract_manager","bronze":8,"silver":2,"gold":1,"name":"Bronze Manager Contract"},
    {"resourceId":5001010,"cardassetid":8,"cardsubtypeid":202,"tier":"bronze","rating":60,"rareflag":1,"kind":"contract_manager","bronze":15,"silver":6,"gold":3,"name":"Rare Bronze Manager Contract"},
    {"resourceId":5001008,"cardassetid":8,"cardsubtypeid":202,"tier":"silver","rating":65,"rareflag":0,"kind":"contract_manager","bronze":8,"silver":10,"gold":8,"name":"Silver Manager Contract"},
    {"resourceId":5001011,"cardassetid":8,"cardsubtypeid":202,"tier":"silver","rating":70,"rareflag":1,"kind":"contract_manager","bronze":18,"silver":24,"gold":18,"name":"Rare Silver Manager Contract"},
    {"resourceId":5001009,"cardassetid":8,"cardsubtypeid":202,"tier":"gold","rating":80,"rareflag":0,"kind":"contract_manager","bronze":11,"silver":11,"gold":13,"name":"Gold Manager Contract"},
    {"resourceId":5001012,"cardassetid":8,"cardsubtypeid":202,"tier":"gold","rating":90,"rareflag":1,"kind":"contract_manager","bronze":24,"silver":24,"gold":28,"name":"Rare Gold Manager Contract"},
    # Player/squad fitness
    {"resourceId":5002001,"cardassetid":10,"cardsubtypeid":219,"tier":"bronze","rating":55,"rareflag":0,"kind":"fitness_player","amount":20,"name":"Bronze Player Fitness"},
    {"resourceId":5002004,"cardassetid":10,"cardsubtypeid":220,"tier":"bronze","rating":55,"rareflag":1,"kind":"fitness_team","amount":10,"name":"Bronze Squad Fitness"},
    {"resourceId":5002002,"cardassetid":10,"cardsubtypeid":219,"tier":"silver","rating":70,"rareflag":0,"kind":"fitness_player","amount":40,"name":"Silver Player Fitness"},
    {"resourceId":5002005,"cardassetid":10,"cardsubtypeid":220,"tier":"silver","rating":70,"rareflag":1,"kind":"fitness_team","amount":20,"name":"Silver Squad Fitness"},
    {"resourceId":5002003,"cardassetid":10,"cardsubtypeid":219,"tier":"gold","rating":80,"rareflag":0,"kind":"fitness_player","amount":60,"name":"Gold Player Fitness"},
    {"resourceId":5002006,"cardassetid":10,"cardsubtypeid":220,"tier":"gold","rating":80,"rareflag":1,"kind":"fitness_team","amount":30,"name":"Gold Squad Fitness"},
    # Healing (one common body-region card + rare all-injury card per tier)
    {"resourceId":5002007,"cardassetid":9,"cardsubtypeid":211,"tier":"bronze","rating":55,"rareflag":0,"kind":"healing","amount":1,"name":"Bronze Healing"},
    {"resourceId":5002028,"cardassetid":9,"cardsubtypeid":218,"tier":"bronze","rating":60,"rareflag":1,"kind":"healing","amount":1,"name":"Rare Bronze All Healing"},
    {"resourceId":5002008,"cardassetid":9,"cardsubtypeid":211,"tier":"silver","rating":70,"rareflag":0,"kind":"healing","amount":2,"name":"Silver Healing"},
    {"resourceId":5002029,"cardassetid":9,"cardsubtypeid":218,"tier":"silver","rating":74,"rareflag":1,"kind":"healing","amount":2,"name":"Rare Silver All Healing"},
    {"resourceId":5002009,"cardassetid":9,"cardsubtypeid":211,"tier":"gold","rating":80,"rareflag":0,"kind":"healing","amount":5,"name":"Gold Healing"},
    {"resourceId":5002030,"cardassetid":9,"cardsubtypeid":218,"tier":"gold","rating":85,"rareflag":1,"kind":"healing","amount":4,"name":"Rare Gold All Healing"},
    # Player training
    {"resourceId":5003022,"cardassetid":1,"cardsubtypeid":61,"tier":"bronze","rating":55,"rareflag":0,"kind":"training_player","amount":5,"name":"Bronze Player Training"},
    {"resourceId":5003040,"cardassetid":1,"cardsubtypeid":67,"tier":"bronze","rating":64,"rareflag":1,"kind":"training_player","amount":3,"name":"Rare Bronze All Training"},
    {"resourceId":5003023,"cardassetid":1,"cardsubtypeid":61,"tier":"silver","rating":65,"rareflag":0,"kind":"training_player","amount":10,"name":"Silver Player Training"},
    {"resourceId":5003041,"cardassetid":1,"cardsubtypeid":67,"tier":"silver","rating":74,"rareflag":1,"kind":"training_player","amount":6,"name":"Rare Silver All Training"},
    {"resourceId":5003024,"cardassetid":1,"cardsubtypeid":61,"tier":"gold","rating":85,"rareflag":0,"kind":"training_player","amount":15,"name":"Gold Player Training"},
    {"resourceId":5003042,"cardassetid":1,"cardsubtypeid":67,"tier":"gold","rating":95,"rareflag":1,"kind":"training_player","amount":10,"name":"Rare Gold All Training"},
]

# Additional common healing/training definitions give standard packs enough variety to avoid
# repeating the same contract/fitness card several times in one 12-item pack.
CONSUMABLE_CATALOG.extend([
    {"resourceId":5002010,"cardassetid":9,"cardsubtypeid":212,"tier":"bronze","rating":55,"rareflag":0,"kind":"healing","amount":1,"name":"Bronze Upper Body Healing"},
    {"resourceId":5002013,"cardassetid":9,"cardsubtypeid":213,"tier":"bronze","rating":55,"rareflag":0,"kind":"healing","amount":1,"name":"Bronze Arm Healing"},
    {"resourceId":5002019,"cardassetid":9,"cardsubtypeid":215,"tier":"bronze","rating":55,"rareflag":0,"kind":"healing","amount":1,"name":"Bronze Knee Healing"},
    {"resourceId":5002022,"cardassetid":9,"cardsubtypeid":216,"tier":"bronze","rating":55,"rareflag":0,"kind":"healing","amount":1,"name":"Bronze Leg Healing"},
    {"resourceId":5002025,"cardassetid":9,"cardsubtypeid":217,"tier":"bronze","rating":55,"rareflag":0,"kind":"healing","amount":1,"name":"Bronze Foot Healing"},
    {"resourceId":5002011,"cardassetid":9,"cardsubtypeid":212,"tier":"silver","rating":70,"rareflag":0,"kind":"healing","amount":2,"name":"Silver Upper Body Healing"},
    {"resourceId":5002014,"cardassetid":9,"cardsubtypeid":213,"tier":"silver","rating":70,"rareflag":0,"kind":"healing","amount":2,"name":"Silver Arm Healing"},
    {"resourceId":5002020,"cardassetid":9,"cardsubtypeid":215,"tier":"silver","rating":70,"rareflag":0,"kind":"healing","amount":2,"name":"Silver Knee Healing"},
    {"resourceId":5002023,"cardassetid":9,"cardsubtypeid":216,"tier":"silver","rating":70,"rareflag":0,"kind":"healing","amount":2,"name":"Silver Leg Healing"},
    {"resourceId":5002026,"cardassetid":9,"cardsubtypeid":217,"tier":"silver","rating":70,"rareflag":0,"kind":"healing","amount":2,"name":"Silver Foot Healing"},
    {"resourceId":5002012,"cardassetid":9,"cardsubtypeid":212,"tier":"gold","rating":80,"rareflag":0,"kind":"healing","amount":5,"name":"Gold Upper Body Healing"},
    {"resourceId":5002015,"cardassetid":9,"cardsubtypeid":213,"tier":"gold","rating":80,"rareflag":0,"kind":"healing","amount":5,"name":"Gold Arm Healing"},
    {"resourceId":5002021,"cardassetid":9,"cardsubtypeid":215,"tier":"gold","rating":80,"rareflag":0,"kind":"healing","amount":5,"name":"Gold Knee Healing"},
    {"resourceId":5002024,"cardassetid":9,"cardsubtypeid":216,"tier":"gold","rating":80,"rareflag":0,"kind":"healing","amount":5,"name":"Gold Leg Healing"},
    {"resourceId":5002027,"cardassetid":9,"cardsubtypeid":217,"tier":"gold","rating":80,"rareflag":0,"kind":"healing","amount":5,"name":"Gold Foot Healing"},
    {"resourceId":5003025,"cardassetid":1,"cardsubtypeid":62,"tier":"bronze","rating":55,"rareflag":0,"kind":"training_player","amount":5,"name":"Bronze Shooting Training"},
    {"resourceId":5003028,"cardassetid":1,"cardsubtypeid":63,"tier":"bronze","rating":55,"rareflag":0,"kind":"training_player","amount":5,"name":"Bronze Passing Training"},
    {"resourceId":5003031,"cardassetid":1,"cardsubtypeid":64,"tier":"bronze","rating":55,"rareflag":0,"kind":"training_player","amount":5,"name":"Bronze Dribbling Training"},
    {"resourceId":5003034,"cardassetid":1,"cardsubtypeid":65,"tier":"bronze","rating":55,"rareflag":0,"kind":"training_player","amount":5,"name":"Bronze Physical Training"},
    {"resourceId":5003037,"cardassetid":1,"cardsubtypeid":66,"tier":"bronze","rating":55,"rareflag":0,"kind":"training_player","amount":5,"name":"Bronze Defending Training"},
    {"resourceId":5003026,"cardassetid":1,"cardsubtypeid":62,"tier":"silver","rating":65,"rareflag":0,"kind":"training_player","amount":10,"name":"Silver Shooting Training"},
    {"resourceId":5003029,"cardassetid":1,"cardsubtypeid":63,"tier":"silver","rating":65,"rareflag":0,"kind":"training_player","amount":10,"name":"Silver Passing Training"},
    {"resourceId":5003032,"cardassetid":1,"cardsubtypeid":64,"tier":"silver","rating":65,"rareflag":0,"kind":"training_player","amount":10,"name":"Silver Dribbling Training"},
    {"resourceId":5003035,"cardassetid":1,"cardsubtypeid":65,"tier":"silver","rating":65,"rareflag":0,"kind":"training_player","amount":10,"name":"Silver Physical Training"},
    {"resourceId":5003038,"cardassetid":1,"cardsubtypeid":66,"tier":"silver","rating":65,"rareflag":0,"kind":"training_player","amount":10,"name":"Silver Defending Training"},
    {"resourceId":5003027,"cardassetid":1,"cardsubtypeid":62,"tier":"gold","rating":85,"rareflag":0,"kind":"training_player","amount":15,"name":"Gold Shooting Training"},
    {"resourceId":5003030,"cardassetid":1,"cardsubtypeid":63,"tier":"gold","rating":85,"rareflag":0,"kind":"training_player","amount":15,"name":"Gold Passing Training"},
    {"resourceId":5003033,"cardassetid":1,"cardsubtypeid":64,"tier":"gold","rating":85,"rareflag":0,"kind":"training_player","amount":15,"name":"Gold Dribbling Training"},
    {"resourceId":5003036,"cardassetid":1,"cardsubtypeid":65,"tier":"gold","rating":85,"rareflag":0,"kind":"training_player","amount":15,"name":"Gold Physical Training"},
    {"resourceId":5003039,"cardassetid":1,"cardsubtypeid":66,"tier":"gold","rating":85,"rareflag":0,"kind":"training_player","amount":15,"name":"Gold Defending Training"},
])


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOGS / "localfut15.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("localfut15")
log.info("Loaded %d FIFA 15 player definitions", log_player_count)

try:
    _special_pool_counts={}
    for _rid,_meta in PLAYER_DB.items():
        _rf=int(_meta.get("rareflag",0) or 0)
        if _rf>1:
            _special_pool_counts[_rf]=_special_pool_counts.get(_rf,0)+1
    log.info("Special rarity pools: %s", dict(sorted(_special_pool_counts.items())))
except Exception:
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


def now_s() -> int:
    return int(time.time())


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def safe_json(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}


def sha1_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()



# Full consumable definition table used for local My Club filtering/application.
# It is based on the proven legacy FUT consumable schema used by the working PC
# restoration. The resource/card subtype families are shared by this FIFA client;
# resourceGameYear is rewritten to 2015 when loaded.
CONSUMABLE_DEFINITION_PATH = ROOT / "consumable_catalog.json"

def _load_consumable_definitions() -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    # Start with pack-tested definitions so their display names remain friendly.
    for row in CONSUMABLE_CATALOG:
        try:
            rid = int(row.get("resourceId", 0) or 0)
        except Exception:
            continue
        if rid:
            merged[rid] = dict(row)
    try:
        raw = json.loads(CONSUMABLE_DEFINITION_PATH.read_text(encoding="utf-8"))
        rows = raw.get("items", raw) if isinstance(raw, dict) else raw
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    rid = int(row.get("resourceId", 0) or 0)
                except Exception:
                    continue
                if not rid:
                    continue
                base = dict(merged.get(rid, {}))
                # The full catalogue is authoritative for category/subtype/effect.
                base.update(row)
                base["resourceId"] = rid
                base["resourceGameYear"] = 2015
                base.setdefault("rareflag", int(base.get("rareFlag", 0) or 0))
                base.setdefault("rareFlag", int(base.get("rareflag", 0) or 0))
                base.setdefault("quality", str(base.get("tier", base.get("quality", "gold")) or "gold").lower())
                if not base.get("displayName") and not base.get("name"):
                    category = str(base.get("category", "Consumable") or "Consumable")
                    kind = str(base.get("kind", "") or "")
                    base["displayName"] = (kind + " " + category).strip()
                merged[rid] = base
    except Exception as exc:
        log.warning("Could not load full consumable catalogue: %s", exc)
    return list(merged.values())

FULL_CONSUMABLE_CATALOG = _load_consumable_definitions()
CONSUMABLE_BY_RESOURCE: dict[int, dict[str, Any]] = {
    int(row["resourceId"]): row for row in FULL_CONSUMABLE_CATALOG if int(row.get("resourceId", 0) or 0) > 0
}

def _consumable_family_from_definition(definition: dict[str, Any] | None) -> str:
    d = definition or {}
    category = str(d.get("category", "") or "").strip().casefold()
    cls = str(d.get("class", "") or "").strip().casefold()
    if category == "contract":
        return "managercontracts" if cls == "manager" else "contracts"
    if category == "fitness":
        return "fitness"
    if category == "healing":
        return "healing"
    if category in {"training", "gk training"}:
        return "training"
    if category == "positioning":
        return "position"
    if category == "chemistry style":
        return "playstyle"
    if category == "manager league":
        return "managerleague"
    kind = str(d.get("kind", "") or "").lower()
    if kind.startswith("contract_manager"): return "managercontracts"
    if kind.startswith("contract_"): return "contracts"
    if kind.startswith("fitness_"): return "fitness"
    if kind == "healing": return "healing"
    if kind.startswith("training_") or kind.startswith("gk_training"): return "training"
    if kind.startswith("position_"): return "position"
    if kind.startswith("playstyle_"): return "playstyle"
    if kind.startswith("managerleague_"): return "managerleague"
    return "development"

def _consumable_family_from_item(item: dict[str, Any]) -> str:
    try:
        rid = int(item.get("resourceId", 0) or 0)
    except Exception:
        rid = 0
    definition = CONSUMABLE_BY_RESOURCE.get(rid)
    if definition:
        return _consumable_family_from_definition(definition)
    kind = str(item.get("consumableKind", "") or "").lower()
    if kind.startswith("contract_manager"): return "managercontracts"
    if kind.startswith("contract_"): return "contracts"
    if kind.startswith("fitness_"): return "fitness"
    if kind == "healing": return "healing"
    if kind.startswith("training_") or kind.startswith("gk_training"): return "training"
    if kind.startswith("position_"): return "position"
    if kind.startswith("playstyle_"): return "playstyle"
    if kind.startswith("managerleague_"): return "managerleague"
    # Fall back to native card families for older persisted items that predate
    # consumableKind/category metadata.
    try:
        asset = int(item.get("cardassetid", 0) or 0)
    except Exception:
        asset = 0
    return {
        1: "training", 3: "training", 7: "contracts", 8: "managercontracts",
        9: "healing", 10: "fitness", 32: "managerleague", 34: "position",
        50: "playstyle",
    }.get(asset, "development")


# Exact FIFA 15 FUT club-identity catalogue.  v0.2.26 generated synthetic
# resource IDs for most badges/kits/stadiums; the client has no matching card
# definitions for those IDs and therefore rendered the bright green NOT FOUND
# placeholder.  v0.2.27 ships definitions extracted from this build's own
# cards_ng_db.db instead.
CLUB_IDENTITY_CATALOG_PATH = ROOT / "club_identity_catalog.json"

def _club_cosmetic_catalog() -> list[dict[str, Any]]:
    try:
        raw = json.loads(CLUB_IDENTITY_CATALOG_PATH.read_text(encoding="utf-8"))
        rows = raw.get("items", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise ValueError("catalogue root is not a list")
        cleaned: list[dict[str, Any]] = []
        seen: set[int] = set()
        for spec0 in rows:
            if not isinstance(spec0, dict):
                continue
            spec = dict(spec0)
            rid = int(spec.get("resourceId", 0) or 0)
            if rid <= 0 or rid in seen:
                continue
            spec["resourceId"] = rid
            # The baked retail catalogue marks defaults separately.  Do not
            # make every catalogue item active merely by inserting it.
            spec["itemState"] = "free"
            cleaned.append(spec)
            seen.add(rid)
        if not cleaned:
            raise ValueError("catalogue contains no usable items")
        return cleaned
    except Exception as exc:
        log.error("CLUB IDENTITY exact catalogue could not be loaded: %s", exc)
        # Known-good retail fallbacks so an install remains bootable even if
        # the catalogue file is accidentally deleted.
        return [
            {"resourceId":6200058,"assetId":261,"stadiumid":261,"cardassetid":36,"cardsubtypeid":10,"itemType":"stadium","family":"stadiums","table":"fcc_stadium","itemState":"free","rating":64,"rareflag":0,"category":4,"displayName":"Sanderson Park","defaultActiveState":"activeStadium"},
            {"resourceId":6300074,"assetId":14,"teamid":1,"cardassetid":35,"cardsubtypeid":9,"itemType":"kit","family":"kits","table":"fcc_kitcards","itemState":"free","rating":83,"rareflag":1,"category":2,"displayName":"Arsenal Home","defaultActiveState":"activeHomeKit"},
            {"resourceId":6400057,"assetId":15,"teamid":1,"cardassetid":35,"cardsubtypeid":9,"itemType":"kit","family":"kits","table":"fcc_kitcards","itemState":"free","rating":83,"rareflag":1,"category":3,"displayName":"Arsenal Away","defaultActiveState":"activeAwayKit"},
            {"resourceId":6000057,"assetId":1,"teamid":1,"cardassetid":39,"cardsubtypeid":11,"itemType":"custom","family":"badges","table":"fcc_badgecards","itemState":"free","rating":83,"rareflag":1,"category":1,"displayName":"Arsenal","defaultActiveState":"activeBadge"},
            {"resourceId":8120212,"assetId":191,"ballid":191,"cardassetid":37,"cardsubtypeid":30,"itemType":"ball","family":"balls","table":"fcc_balls","itemState":"free","rating":74,"rareflag":0,"category":1,"displayName":"Ball 191","defaultActiveState":"activeBall"},
        ]

CLUB_COSMETIC_CATALOG = _club_cosmetic_catalog()
CLUB_COSMETIC_BY_RESOURCE = {int(x["resourceId"]): x for x in CLUB_COSMETIC_CATALOG}


class State:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self.lock:
            c = self.conn.cursor()
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS items(
                    id INTEGER PRIMARY KEY,
                    resource_id INTEGER NOT NULL,
                    pile TEXT NOT NULL DEFAULT 'club',
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS squads(
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS unopened_packs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pack_id INTEGER NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auctions(
                    trade_id INTEGER PRIMARY KEY,
                    item_id INTEGER NOT NULL DEFAULT 0,
                    resource_id INTEGER NOT NULL,
                    seller_is_user INTEGER NOT NULL DEFAULT 1,
                    starting_bid INTEGER NOT NULL DEFAULT 0,
                    buy_now INTEGER NOT NULL DEFAULT 0,
                    current_bid INTEGER NOT NULL DEFAULT 0,
                    created INTEGER NOT NULL DEFAULT 0,
                    expires INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'active',
                    credited INTEGER NOT NULL DEFAULT 0,
                    data TEXT NOT NULL DEFAULT '{}',
                    sold_price INTEGER NOT NULL DEFAULT 0,
                    sold_at INTEGER NOT NULL DEFAULT 0,
                    auto_sell_after INTEGER NOT NULL DEFAULT 0,
                    market_value_at_list INTEGER NOT NULL DEFAULT 0,
                    item_payload TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            # Non-destructive schema migration for v0.2.29 and older saves.
            auction_columns = {str(row[1]) for row in c.execute("PRAGMA table_info(auctions)").fetchall()}
            for col_name, declaration in (
                ("sold_price", "INTEGER NOT NULL DEFAULT 0"),
                ("sold_at", "INTEGER NOT NULL DEFAULT 0"),
                ("auto_sell_after", "INTEGER NOT NULL DEFAULT 0"),
                ("market_value_at_list", "INTEGER NOT NULL DEFAULT 0"),
                ("item_payload", "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if col_name not in auction_columns:
                    c.execute(f"ALTER TABLE auctions ADD COLUMN {col_name} {declaration}")
            self.conn.commit()
            self.set_default("credits", int(CFG["credits"]))
            # Club identity belongs to the save, not to the build's config.json.
            # This fixes names/abbreviations reverting whenever the user upgrades.
            self.set_default("club_name", str(CFG.get("club_name", "Local FC")))
            self.set_default("club_abbr", str(CFG.get("club_abbr", "LCL")))
            self.set_default("persona_name", str(CFG.get("display_name", "LocalPlayer")))
            self.set_default("next_item_id", 900000000000)
            self.set_default("sid", "LOCAL15-" + sha1_text(str(time.time()))[:20].upper())
            self.set_default("token", "LOCAL15TOKEN-" + sha1_text(str(time.time() + 1))[:24].upper())
            self.set_default("established", now_s())
            # Existing migrated clubs are returning clubs.  New clean installs keep
            # the flag false until the first explicit club-name confirmation.
            existing_name = str(self.get("club_name", CFG.get("club_name", "Local FC")) or "Local FC")
            existing_abbr = str(self.get("club_abbr", CFG.get("club_abbr", "LCL")) or "LCL")
            self.set_default("club_setup_complete", bool(existing_name != "Local FC" or existing_abbr != "LCL"))
            self.set_default("next_trade_id", 650000000000)
            self.set_default("offline_season_division", 10)
            self.set_default("offline_season_points", 0)
            self.set_default("offline_season_round", 0)
            self.set_default("offline_season_wins", 0)
            self.set_default("offline_season_draws", 0)
            self.set_default("offline_season_losses", 0)
            self.set_default("offline_season_goals_for", 0)
            self.set_default("offline_season_goals_against", 0)
            self.set_default("offline_season_trophies", 0)
            # Persist the FUT header record independently of the current division.
            # Existing v0.2.16 profiles are seeded from their already-settled
            # offline-season result so the first successful match is not lost
            # when upgrading to this post-match hotfix.
            self.set_default("record_wins", int(self.get("offline_season_wins", 0) or 0))
            self.set_default("record_draws", int(self.get("offline_season_draws", 0) or 0))
            self.set_default("record_losses", int(self.get("offline_season_losses", 0) or 0))
            self.set_default("offline_seasons_completed", 0)
            self.set_default("offline_season_promotions", 0)
            self.set_default("offline_season_relegations", 0)
            self.set_default("offline_season_coins", 0)
            self.set_default("offline_season_history_goals_for", 0)
            self.set_default("offline_season_history_goals_against", 0)
            self.set_default("last_match_end_response", {})
            self.set_default("offline_match_starters", [])
            # A current-season record must not be fabricated before FIFA has
            # actually started one. v0.2.8 always returned season/user round 1,
            # which made the PC client try to resume a season with no save data.
            self.set_default("offline_season_active", False)
            # v0.2.13 initially stored FIFA's bootstrap season-save round=1 as if
            # one match had already been played. That made the next launch advertise
            # round 2 even though the user's W/D/L and points were still untouched.
            # Repair only that unambiguous zero-game state; real played matches have
            # either a W/D/L count or points and are left alone.
            try:
                if (
                    bool(self.get("offline_season_active", False))
                    and int(self.get("offline_season_round", 0) or 0) == 1
                    and int(self.get("offline_season_points", 0) or 0) == 0
                    and int(self.get("offline_season_wins", 0) or 0) == 0
                    and int(self.get("offline_season_draws", 0) or 0) == 0
                    and int(self.get("offline_season_losses", 0) or 0) == 0
                ):
                    self.set("offline_season_round", 0)
                    log.warning("SEASONS MIGRATION repaired bootstrap round 1 -> 0 (no match result recorded)")
            except Exception as exc:
                log.warning("SEASONS MIGRATION skipped: %s", exc)

            # v0.2.17 deliberately discarded opaque SeasonData after a forfeit.
            # That preserved the SQLite W/D/L but left FIFA with nothing capable
            # of rendering the active fixture table, so the frontend appeared to
            # start a brand-new season. Do not delete client-authored SeasonData.
            #
            # Existing profiles that already lost their opaque save cannot have
            # that binary state reconstructed safely. Align only the *current*
            # season counters with the fresh season FIFA is already displaying,
            # while preserving the all-time FUT record. This is a one-time v218
            # recovery and prevents old test W/D/L from fighting the new client
            # save authored after the next match.
            try:
                migration = int(self.get("season_persistence_schema", 0) or 0)
                if migration < 218:
                    played = int(self.get("offline_season_round", 0) or 0)
                    saved_data = str(self.get("offline_season_wire_data", "") or "")
                    if bool(self.get("offline_season_active", False)) and played > 0 and not saved_data:
                        for key in (
                            "offline_season_points", "offline_season_round",
                            "offline_season_wins", "offline_season_draws", "offline_season_losses",
                            "offline_season_goals_for", "offline_season_goals_against",
                        ):
                            self.set(key, 0)
                        self.set("offline_season_wire_round", 1)
                        self.set("offline_season_wire_progress_data", "")
                        self.set("last_match_end_response", {})
                        self.set("offline_match_pending", False)
                        log.warning(
                            "SEASONS v0.2.18 recovery aligned current season to fresh client state; "
                            "all-time record preserved"
                        )
                    self.set("season_persistence_schema", 218)
            except Exception as exc:
                log.warning("SEASONS v0.2.18 recovery skipped: %s", exc)

            self.set_default("awaiting_post_match_season_save", False)

            # v0.2.18-v0.2.20 could advance semantic W/D/L after a forfeit while
            # preserving a pre-match opaque SeasonData blob. FIFA then rendered a
            # fresh Start Season screen even though SQLite said Round 2/3/4. That
            # split-brain state cannot be reconstructed reliably because the opaque
            # client blob contains the fixture table/result flags. Realign only the
            # CURRENT test season once on upgrade; preserve the all-time FUT record,
            # club, coins and every item. New forfeits are terminally acknowledged as
            # LOSS below so FIFA authors a genuine next-round blob instead.
            try:
                migration = int(self.get("season_persistence_schema", 0) or 0)
                if migration < 221:
                    played = int(self.get("offline_season_round", 0) or 0)
                    if played > 0:
                        for key in (
                            "offline_season_points", "offline_season_round",
                            "offline_season_wins", "offline_season_draws", "offline_season_losses",
                            "offline_season_goals_for", "offline_season_goals_against",
                        ):
                            self.set(key, 0)
                        self.set("offline_season_active", False)
                        self.set("offline_season_wire_round", 1)
                        self.set("offline_season_wire_data", "")
                        self.set("offline_season_wire_progress_data", "")
                        self.set("awaiting_post_match_season_save", False)
                        self.set("offline_match_pending", False)
                        self.set("last_match_end_response", {})
                        log.warning(
                            "SEASONS v0.2.21 migration realigned corrupted current season to fresh Division 10; "
                            "all-time FUT record preserved"
                        )
                    self.set("season_persistence_schema", 221)
            except Exception as exc:
                log.warning("SEASONS v0.2.21 migration skipped: %s", exc)

            # v0.2.24 repeats the requested one-time clean Seasons reset after the v0.2.23 client-crash regression
            # for the first proper win/progression verification. Keep the club,
            # squad, coins, items and all-time FUT record untouched, but throw away
            # only the current offline-season counters/native opaque save. Force the
            # new season to start from human Division 10.
            try:
                migration = int(self.get("season_persistence_schema", 0) or 0)
                if migration < 224:
                    self.set("offline_season_division", 10)
                    for key in (
                        "offline_season_points", "offline_season_round",
                        "offline_season_wins", "offline_season_draws", "offline_season_losses",
                        "offline_season_goals_for", "offline_season_goals_against",
                    ):
                        self.set(key, 0)
                    self.set("offline_season_active", False)
                    self.set("offline_season_wire_round", 1)
                    self.set("offline_season_wire_data", "")
                    self.set("offline_season_wire_data_version", 1)
                    self.set("offline_season_wire_progress_data", "")
                    self.set("offline_season_wire_progress_version", 1)
                    self.set("awaiting_post_match_season_save", False)
                    self.set("offline_match_pending", False)
                    self.set("last_match_end_response", {})
                    self.set("season_persistence_schema", 224)
                    log.warning(
                        "SEASONS v0.2.24 crash-hotfix reset: current season cleared and forced to backend Division 10; "
                        "all-time FUT record/club preserved"
                    )
            except Exception as exc:
                log.warning("SEASONS v0.2.24 reset migration skipped: %s", exc)

            if not self._has_any_items():
                self._seed_items()
            self._enrich_existing_player_items()
            self._normalize_existing_consumables()
            self._seed_club_cosmetics()
            if not self._has_any_squads():
                self._seed_squad()
            # Reconcile item pile membership from the persisted squads on every
            # startup. This makes the SQLite state authoritative after a full
            # game/server restart instead of relying on FIFA to resend the XI.
            with self.lock:
                self._sync_squad_item_piles_locked()
                self.conn.commit()

    def set_default(self, key: str, value: Any) -> None:
        row = self.conn.execute("SELECT 1 FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            self.conn.execute("INSERT INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))
            self.conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        with self.lock:
            row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row[0])
            except Exception:
                return row[0]

    def set(self, key: str, value: Any) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
            self.conn.commit()

    def profile(self) -> dict[str, str]:
        return {
            "clubName": str(self.get("club_name", CFG.get("club_name", "Local FC")) or "Local FC"),
            "clubAbbr": str(self.get("club_abbr", CFG.get("club_abbr", "LCL")) or "LCL"),
            "personaName": str(self.get("persona_name", CFG.get("display_name", "LocalPlayer")) or "LocalPlayer"),
        }

    def update_profile(self, payload: dict[str, Any]) -> dict[str, str]:
        """Persist the editable FUT club identity in the canonical SQLite save."""
        current = self.profile()
        if isinstance(payload, dict):
            if "clubName" in payload:
                name = " ".join(str(payload.get("clubName") or "").strip().split())[:32]
                if name:
                    self.set("club_name", name)
            if "clubAbbr" in payload:
                abbr = "".join(ch for ch in str(payload.get("clubAbbr") or "").strip() if ch.isalnum())[:3]
                if abbr:
                    self.set("club_abbr", abbr)
            if "personaName" in payload:
                persona = " ".join(str(payload.get("personaName") or "").strip().split())[:32]
                if persona:
                    self.set("persona_name", persona)
        updated = self.profile()
        # FIFA 15 treats club-name confirmation as a one-time setup state.
        # Persist completion separately from the editable strings so entering FUT
        # on a later run does not reopen the naming flow.
        self.set("club_setup_complete", True)
        if updated != current:
            log.warning(
                "PROFILE SAVED SQLite clubName=%s clubAbbr=%s personaName=%s setupComplete=1 db=%s",
                updated["clubName"], updated["clubAbbr"], updated["personaName"], self.path,
            )
        return updated

    def credits(self) -> int:
        return int(self.get("credits", 0))

    def add_credits(self, amount: int) -> int:
        v = max(0, self.credits() + int(amount))
        self.set("credits", v)
        return v

    def sid(self) -> str:
        return str(self.get("sid"))

    def token(self) -> str:
        return str(self.get("token"))

    def _has_any_items(self) -> bool:
        return self.conn.execute("SELECT 1 FROM items LIMIT 1").fetchone() is not None

    def _has_any_squads(self) -> bool:
        return self.conn.execute("SELECT 1 FROM squads LIMIT 1").fetchone() is not None

    def next_item_id(self) -> int:
        with self.lock:
            v = int(self.get("next_item_id", 900000000000)) + 1
            self.set("next_item_id", v)
            return v

    def player_discard_value(self, resource_id: int) -> int:
        """Local FUT quick-sell values.

        User-selected economy:
          common/base non-rare = 360
          base rare            = 700
          special              = 10,000-17,000 based on card rarity/type
        """
        meta = player_meta(resource_id)
        try:
            rareflag = int(meta.get("rareflag", 0) or 0)
        except Exception:
            rareflag = 0

        is_special = bool(meta.get("special", False)) or rareflag > 1

        if not is_special:
            return 700 if rareflag == 1 else 360

        rating = int(meta.get("rating", 75) or 75)

        # FIFA 15 special shells. IF/TOTW quick-sell now scales by OVR so an
        # ordinary low-rated IF sits around 10k while strong IFs reach ~14k.
        # This also gives the AI market a meaningful hard floor when pricing
        # specials instead of listing them below their own discard value.
        if rareflag == 3:  # IF / TOTW
            return int(min(14000, max(10000, 10000 + max(0, rating - 75) * 500)))

        special_values = {
            4: 11500,   # Hero / Purple
            5: 17000,   # TOTY
            6: 13500,   # Record Breaker
            7: 11000,   # St Patrick / Green
            8: 12500,   # MOTM / Orange
            9: 12000,   # FUTTIES / Pink
            10: 12000,  # Teal / other special
            11: 16000,  # TOTS
            12: 15000,  # Legend
            13: 13500,
            14: 13500,
        }
        return int(special_values.get(rareflag, 12000))

    def make_player_item(self, resource_id: int, pile: str = "club") -> dict[str, Any]:
        item_id = self.next_item_id()
        meta = player_meta(resource_id)
        # Keep the instance fields native, but also include the FIFA 15 base-card
        # metadata needed by the client during pack reveals and club rendering.
        item = {
            "id": item_id,
            "timestamp": now_s(),
            "resourceId": int(resource_id),
            "assetId": int(meta.get("assetId", resource_id)),
            "rating": int(meta.get("rating", 0)),
            "itemState": "free",
            "rareflag": int(meta.get("rareflag", CFG.get("rare_flag", 1))),
            "formation": "f442",
            "leagueId": int(meta.get("leagueId", 0)),
            "injuryType": "none",
            "injuryGames": 0,
            "lastSalePrice": 0,
            "fitness": 99,
            "training": 0,
            "suspension": 0,
            "contract": 7,
            "contracts": 7,
            "preferredPosition": str(meta.get("preferredPosition", "")),
            "playStyle": 0,
            "discardValue": self.player_discard_value(resource_id),
            "itemType": "player",
            "cardsubtypeid": 1,
            "owners": 1,
            "untradeable": False,
            "morale": 50,
            "statsList": [],
            "lifetimeStats": [],
            "attributeList": player_attribute_list(resource_id),
            "teamid": int(meta.get("teamid", 0)),
            "assists": 0,
            "lifetimeAssists": 0,
            "loyaltyBonus": 1,
            "pile": pile,
            "nation": int(meta.get("nation", 0)),
            "resourceGameYear": 2015,
            "marketDataMinPrice": 150,
            "marketDataMaxPrice": 15000000,
        }
        with self.lock:
            self.conn.execute(
                "INSERT INTO items(id,resource_id,pile,data) VALUES(?,?,?,?)",
                (item_id, int(resource_id), pile, json.dumps(item)),
            )
            self.conn.commit()
        return item

    def make_consumable_item(self, spec: dict[str, Any], pile: str = "unassigned") -> dict[str, Any]:
        """Create one native-ish FUT consumable item instance.

        FIFA 15's static definition is identified by resourceId/cardassetid/cardsubtypeid;
        the category-specific boost fields are carried on the dynamic item as well so the
        Apply Consumable screens have useful data once the card is stored in the club.
        """
        item_id = self.next_item_id()
        rid = int(spec.get("resourceId", 0) or 0)
        definition = dict(CONSUMABLE_BY_RESOURCE.get(rid, {}))
        definition.update(spec)
        spec = definition
        rare = int(spec.get("rareflag", spec.get("rareFlag", 0)) or 0)
        tier = str(spec.get("tier", spec.get("quality", "gold")) or "gold").lower()
        discard = {"bronze": 18, "silver": 32, "gold": 64}.get(tier, 32) * (2 if rare else 1)
        kind = str(spec.get("kind", "consumable") or "consumable")
        item_type = str(spec.get("itemType", "") or "").lower()
        if item_type not in {"development", "training"}:
            item_type = "training" if kind.startswith("training") else "development"
        item = {
            "id": item_id,
            "timestamp": now_s(),
            "resourceId": rid,
            "assetId": rid,
            "cardassetid": int(spec.get("cardassetid", 0) or 0),
            "cardsubtypeid": int(spec.get("cardsubtypeid", 0) or 0),
            "rating": int(spec.get("rating", 0) or 0),
            "itemState": "free",
            "itemType": item_type,
            "rareflag": rare,
            "weightrare": 100 if rare else 0,
            "resourceGameYear": 2015,
            "owners": 1,
            "untradeable": False,
            "lastSalePrice": 0,
            "discardValue": int(discard),
            "pile": pile,
            "amount": int(spec.get("amount", 0) or 0),
            "bronze": int(spec.get("bronze", 0) or 0),
            "silver": int(spec.get("silver", 0) or 0),
            "gold": int(spec.get("gold", 0) or 0),
            "stackCount": 1,
            "consumableKind": kind,
            "category": str(spec.get("category", "") or ""),
            "class": str(spec.get("class", "") or ""),
            "kind": str(spec.get("kind", "") or ""),
            "quality": str(spec.get("quality", tier) or tier),
            "applicationSupported": bool(spec.get("applicationSupported", True)),
            "displayName": str(spec.get("displayName", spec.get("name", "Consumable")) or "Consumable"),
            "marketDataMinPrice": 150,
            "marketDataMaxPrice": 15000000,
        }
        # Native category counters/boost fields used by the old FUT client.
        if kind == "contract_player": item["consumablesContractPlayer"] = 1
        elif kind == "contract_manager": item["consumablesContractManager"] = 1
        elif kind == "fitness_player": item["consumablesFitnessPlayer"] = int(spec.get("amount", 0) or 0)
        elif kind == "fitness_team": item["consumablesFitnessTeam"] = int(spec.get("amount", 0) or 0)
        elif kind == "healing": item["consumablesHealing"] = int(spec.get("amount", 0) or 0)
        elif kind == "training_player":
            item["consumablesTraining"] = 1
            item["consumablesTrainingPlayer"] = int(spec.get("amount", 0) or 0)
        with self.lock:
            self.conn.execute(
                "INSERT INTO items(id,resource_id,pile,data) VALUES(?,?,?,?)",
                (item_id, rid, pile, json.dumps(item)),
            )
            self.conn.commit()
        return item

    def make_club_item(self, spec: dict[str, Any], pile: str = "club") -> dict[str, Any]:
        item_id = self.next_item_id()
        item = dict(spec)
        item.update({
            "id": item_id, "timestamp": now_s(), "pile": pile,
            "resourceGameYear": 2015, "owners": 1, "untradeable": False,
            "discardValue": int(item.get("discardValue", 10) or 10),
            "lastSalePrice": int(item.get("lastSalePrice", 0) or 0),
            "weightrare": 100 if int(item.get("rareflag", 0) or 0) else 0,
            "marketDataMinPrice": 150, "marketDataMaxPrice": 15000000,
        })
        rid = int(item.get("resourceId", 0) or 0)
        with self.lock:
            self.conn.execute("INSERT INTO items(id,resource_id,pile,data) VALUES(?,?,?,?)", (item_id, rid, pile, json.dumps(item)))
            self.conn.commit()
        return item

    def _seed_club_cosmetics(self) -> None:
        schema = int(self.get("club_cosmetic_schema", 0) or 0)
        if schema >= 227:
            return

        # Remove the v0.2.26 synthetic identity cards.  Their resource IDs do
        # not exist in FIFA 15's cards_ng_db and are exactly what produced the
        # green NOT FOUND cards.  These ranges cannot collide with the retail
        # IDs used by the exact catalogue below.
        def is_v226_synthetic(rid: int) -> bool:
            return (
                610000000 <= rid < 611000000 or
                630000000 <= rid < 631000000 or
                640000000 <= rid < 641000000 or
                6220000 <= rid < 6230000
            )

        removed = 0
        with self.lock:
            rows = self.conn.execute("SELECT id,resource_id FROM items").fetchall()
            bad_ids = [int(r["id"]) for r in rows if is_v226_synthetic(int(r["resource_id"] or 0))]
            if bad_ids:
                self.conn.executemany("DELETE FROM items WHERE id=?", [(iid,) for iid in bad_ids])
                removed = len(bad_ids)
                self.conn.commit()

        existing = {int(x.get("resourceId", 0) or 0) for x in self.list_items()}
        added = 0
        # Public-test installs deliberately start barebones: one badge, home/away
        # kit pair, stadium and ball. Full developer builds can still seed the
        # complete retail cosmetic catalogue by leaving starter_cosmetics_only false.
        starter_identity_ids = {6000057, 6300074, 6400057, 6200058, 8120212}
        seed_catalog = (
            [x for x in CLUB_COSMETIC_CATALOG if int(x.get("resourceId", 0) or 0) in starter_identity_ids]
            if bool(CFG.get("starter_cosmetics_only", False))
            else CLUB_COSMETIC_CATALOG
        )
        for spec0 in seed_catalog:
            spec = dict(spec0)
            rid = int(spec.get("resourceId", 0) or 0)
            if rid and rid not in existing:
                # Seed as inactive; active identity is repaired below.
                spec["itemState"] = "free"
                self.make_club_item(spec, "club")
                existing.add(rid)
                added += 1

        # If an active identity pointed to a removed synthetic card, restore a
        # real retail default.  Existing valid user selections are preserved.
        default_active = {
            "activeBadge": 6000057,
            "activeHomeKit": 6300074,
            "activeAwayKit": 6400057,
            "activeStadium": 6200058,
            "activeBall": 8120212,
        }
        with self.lock:
            rows = self.conn.execute("SELECT id,resource_id,data FROM items WHERE pile='club'").fetchall()
            states = set()
            by_rid = {}
            for row in rows:
                data = json.loads(row["data"])
                states.add(str(data.get("itemState", "")))
                by_rid[int(row["resource_id"] or 0)] = (int(row["id"]), data)
            for state, rid in default_active.items():
                if state in states or rid not in by_rid:
                    continue
                iid, data = by_rid[rid]
                data["itemState"] = state
                self.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(data), iid))
            self.conn.commit()

        self.set("club_cosmetic_schema", 227)
        log.warning(
            "CLUB IDENTITY v227 exact retail migration removed=%d seeded=%d catalogue=%d",
            removed, added, len(CLUB_COSMETIC_CATALOG),
        )

    def decrement_player_contracts(self, item_ids: list[int]) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        seen: set[int] = set()
        for iid0 in item_ids:
            iid = int(iid0 or 0)
            if iid <= 0 or iid in seen:
                continue
            seen.add(iid)
            item = self.get_item(iid)
            if not item or str(item.get("itemType", "player")) != "player":
                continue
            old = int(item.get("contract", item.get("contracts", 0)) or 0)
            new = max(0, old - 1)
            updated = self.update_item_fields(iid, {"contract": new, "contracts": new})
            if updated:
                changed.append(updated)
        return changed

    def equip_club_item(self, item_id: int) -> dict[str, Any] | None:
        item = self.get_item(int(item_id))
        if not item:
            return None
        typ = str(item.get("itemType", "")).lower()
        category = int(item.get("category", 0) or 0)
        state = None
        if typ == "stadium": state = "activeStadium"
        elif typ == "custom": state = "activeBadge"
        elif typ == "ball": state = "activeBall"
        elif typ == "kit" and category == 2: state = "activeHomeKit"
        elif typ == "kit" and category == 3: state = "activeAwayKit"
        if not state:
            return None
        with self.lock:
            rows = self.conn.execute("SELECT id,data FROM items WHERE pile='club'").fetchall()
            for row in rows:
                data = json.loads(row["data"]); cur = str(data.get("itemState", ""))
                if cur == state:
                    data["itemState"] = "free"
                    self.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(data), int(row["id"])))
            item["itemState"] = state
            self.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(item), int(item_id)))
            self.conn.commit()
        log.warning("CLUB IDENTITY equipped id=%s type=%s state=%s name=%s", item_id, typ, state, item.get("displayName", ""))
        return item

    def _enrich_existing_player_items(self) -> None:
        """Backfill FIFA 15 metadata into items created by older 0-rated builds."""
        with self.lock:
            rows = self.conn.execute("SELECT id, resource_id, data FROM items").fetchall()
            changed = 0
            for row in rows:
                rid = int(row["resource_id"])
                meta = player_meta(rid)
                if not meta:
                    continue
                data = json.loads(row["data"])
                data["rating"] = int(meta.get("rating", data.get("rating", 0)))
                data["preferredPosition"] = str(meta.get("preferredPosition", data.get("preferredPosition", "")))
                data["leagueId"] = int(meta.get("leagueId", data.get("leagueId", 0)))
                data["teamid"] = int(meta.get("teamid", data.get("teamid", 0)))
                data["nation"] = int(meta.get("nation", data.get("nation", 0)))
                data["rareflag"] = int(meta.get("rareflag", data.get("rareflag", CFG.get("rare_flag", 1))) or 0)
                data["discardValue"] = self.player_discard_value(rid)
                # A training card is a one-match temporary boost. Preserve its
                # boosted face attributes across a server/game restart until that
                # player's next settled match; otherwise refresh from base metadata.
                training_active = int(data.get("training", 0) or 0) > 0 and isinstance(data.get("trainingBaseAttributeList"), list)
                if not training_active:
                    data["attributeList"] = player_attribute_list(rid)
                    data.pop("trainingBaseAttributeList", None)
                    data.pop("trainingResourceId", None)
                    data.pop("trainingExpiresAfterMatch", None)
                self.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(data), int(row["id"])))
                changed += 1
            if changed:
                self.conn.commit()
                log.info("Enriched %d existing FUT player items with FIFA 15 metadata", changed)

    def _seed_items(self) -> None:
        for rid in list(CFG.get("starter_players", []))[:14]:
            self.make_player_item(int(rid), "club")

    def list_items(self, pile: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            if pile:
                rows = self.conn.execute("SELECT data FROM items WHERE pile=? ORDER BY id", (pile,)).fetchall()
            else:
                rows = self.conn.execute("SELECT data FROM items ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def transfer_list_items(self) -> list[dict[str, Any]]:
        """Return every persistent Transfer List item, listed or unlisted.

        FIFA 15 sends item PUTs using pile=trade when the user selects
        "Send to Transfer List". v0.2.27 only rendered rows from the auctions
        table, so those successfully-moved cards disappeared from /tradePile and
        the UI stayed at 0/100. Accept the old internal tradepile spelling too so
        listings made by older builds migrate without losing a card.
        """
        with self.lock:
            rows = self.conn.execute(
                "SELECT id,pile,data FROM items WHERE pile IN ('trade','tradepile') ORDER BY id"
            ).fetchall()
            out: list[dict[str, Any]] = []
            legacy: list[tuple[str, int]] = []
            for row in rows:
                try:
                    data = json.loads(row["data"])
                except Exception:
                    continue
                if str(row["pile"]) == "tradepile":
                    data["pile"] = "trade"
                    legacy.append((json.dumps(data), int(row["id"])))
                out.append(data)
            if legacy:
                self.conn.executemany("UPDATE items SET pile='trade', data=? WHERE id=?", legacy)
                self.conn.commit()
                log.info("TRANSFER LIST migrated %d legacy tradepile item(s) -> trade", len(legacy))
        return out

    def transfer_list_count(self) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM items WHERE pile IN ('trade','tradepile')"
            ).fetchone()
        return int(row[0] if row else 0)

    def user_auction_for_item(self, item_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM auctions WHERE seller_is_user=1 AND item_id=? ORDER BY trade_id DESC LIMIT 1",
                (int(item_id),),
            ).fetchone()
        return dict(row) if row else None

    def update_item_pile(self, item_id: int, pile: str) -> bool:
        with self.lock:
            row = self.conn.execute("SELECT data FROM items WHERE id=?", (int(item_id),)).fetchone()
            if not row:
                return False
            data = json.loads(row[0])
            data["pile"] = pile
            self.conn.execute("UPDATE items SET pile=?, data=? WHERE id=?", (pile, json.dumps(data), int(item_id)))
            self.conn.commit()
            return True

    def update_item_fields(self, item_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Persist mutable player/item state supplied by native FUT updates."""
        safe = {
            "contract", "contracts", "fitness", "morale", "injuryGames", "injuryType",
            "training", "suspension", "preferredPosition", "playStyle", "formation",
            "shots", "goals", "yellowCards", "redCards", "assists", "lifetimeAssists",
            "statsList", "lifetimeStats", "attributeList", "posMods",
        }
        with self.lock:
            row = self.conn.execute("SELECT pile,data FROM items WHERE id=?", (int(item_id),)).fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["data"])
            except Exception:
                return None
            for key in safe:
                if key in changes:
                    data[key] = changes[key]
            if "contract" in changes and "contracts" not in changes:
                data["contracts"] = changes["contract"]
            if "contracts" in changes and "contract" not in changes:
                data["contract"] = changes["contracts"]
            self.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(data), int(item_id)))
            self.conn.commit()
            return data

    def expire_training_for_items(self, item_ids: list[int]) -> list[dict[str, Any]]:
        """Expire one-match player/GK training after a settled match.

        Restore the exact base face attributes captured when the training card
        was applied, clear the native `training` indicator and persist the card.
        """
        expired: list[dict[str, Any]] = []
        wanted = {int(x) for x in item_ids if int(x) > 0}
        if not wanted:
            return expired
        with self.lock:
            for iid in wanted:
                row = self.conn.execute("SELECT data FROM items WHERE id=?", (iid,)).fetchone()
                if not row:
                    continue
                try:
                    item = json.loads(row["data"])
                except Exception:
                    continue
                base = item.get("trainingBaseAttributeList")
                if int(item.get("training", 0) or 0) <= 0 or not isinstance(base, list):
                    continue
                item["attributeList"] = [dict(x) for x in base if isinstance(x, dict)]
                item["training"] = 0
                item.pop("trainingBaseAttributeList", None)
                item.pop("trainingResourceId", None)
                item.pop("trainingExpiresAfterMatch", None)
                self.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(item), iid))
                expired.append(item)
            if expired:
                self.conn.commit()
        if expired:
            log.warning("CONSUMABLE TRAINING EXPIRED next-match items=%s", [int(x.get("id", 0) or 0) for x in expired])
        return expired

    def delete_item(self, item_id: int) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM items WHERE id=?", (int(item_id),))
            self.conn.commit()
            return cur.rowcount > 0

    def discard_items(self, item_ids: list[int]) -> tuple[int, list[int]]:
        """Delete owned item instances and credit their stored server-side values.

        Never trusts a discard value supplied by the FIFA client. Each item is
        looked up in SQLite and its expected value is recalculated from players.json.
        """
        clean_ids = []
        seen = set()
        for raw in item_ids:
            try:
                iid = int(raw)
            except Exception:
                continue
            if iid > 0 and iid not in seen:
                seen.add(iid)
                clean_ids.append(iid)

        if not clean_ids:
            return self.credits(), []

        payout = 0
        deleted = []

        with self.lock:
            for iid in clean_ids:
                row = self.conn.execute(
                    "SELECT resource_id, data FROM items WHERE id=?",
                    (iid,),
                ).fetchone()
                if not row:
                    continue

                try:
                    data = json.loads(row["data"] if hasattr(row, "keys") else row[1])
                except Exception:
                    data = {}

                # Do not allow squad-bound cards to disappear through an odd client call.
                pile = str(data.get("pile", ""))
                if pile == "squad":
                    log.warning("Refused discard of squad-bound item %d", iid)
                    continue

                # Transfer List cards may carry a persistent auction row.  A
                # quick-sell of an expired/inactive card must remove BOTH the item
                # and that auction snapshot; otherwise /tradePile resurrects the
                # deleted player from auctions.item_payload after paying coins.
                auction_rows = self.conn.execute(
                    "SELECT trade_id,state FROM auctions WHERE seller_is_user=1 AND item_id=?",
                    (iid,),
                ).fetchall()
                if any(str(a["state"] if hasattr(a, "keys") else a[1]) == "active" for a in auction_rows):
                    log.warning("Refused discard of actively listed Transfer List item %d", iid)
                    continue
                if auction_rows:
                    self.conn.execute(
                        "DELETE FROM auctions WHERE seller_is_user=1 AND item_id=?",
                        (iid,),
                    )
                    log.warning(
                        "QUICKSELL cleaned auction rows item=%s trades=%s",
                        iid, [int(a["trade_id"] if hasattr(a, "keys") else a[0]) for a in auction_rows],
                    )

                try:
                    rid = int(data.get("resourceId", row["resource_id"] if hasattr(row, "keys") else row[0]) or 0)
                except Exception:
                    rid = int(row["resource_id"] if hasattr(row, "keys") else row[0])

                if str(data.get("itemType", "player")) == "player":
                    value = self.player_discard_value(rid)
                else:
                    value = int(data.get("discardValue", 0) or 0)
                payout += max(0, int(value))

                cur = self.conn.execute("DELETE FROM items WHERE id=?", (iid,))
                if cur.rowcount:
                    deleted.append(iid)

            if deleted and payout:
                current = int(self.get("credits", 0))
                new_total = max(0, current + payout)
                self.conn.execute(
                    "INSERT INTO kv(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("credits", json.dumps(new_total)),
                )
            self.conn.commit()

        log.warning(
            "QUICKSELL items=%s payout=%d newCredits=%d",
            deleted, payout, self.credits()
        )
        return self.credits(), deleted

    def clear_pile(self, pile: str) -> int:
        """Remove all transient items from a pile and return the number removed."""
        with self.lock:
            cur = self.conn.execute("DELETE FROM items WHERE pile=?", (str(pile),))
            self.conn.commit()
            return int(cur.rowcount or 0)

    def owned_player_resource_ids(self) -> set[int]:
        """Return player definitions already owned in the club or a squad.

        Unassigned pack items are intentionally excluded: FIFA's duplicate marker
        should compare a newly opened card against cards the user already owns,
        not against the rest of the current pack reveal.
        """
        owned: set[int] = set()
        for pile in ("club", "squad"):
            for item in self.list_items(pile):
                if str(item.get("itemType", "player")) != "player":
                    continue
                try:
                    rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
                except Exception:
                    rid = 0
                if rid:
                    owned.add(rid)
        return owned

    def owned_player_item_by_resource_id(self, resource_id: int) -> dict[str, Any] | None:
        """Return an already-owned club/squad item for a player definition."""
        rid = int(resource_id or 0)
        if not rid:
            return None
        for pile in ("club", "squad"):
            for item in self.list_items(pile):
                if str(item.get("itemType", "player")) != "player":
                    continue
                try:
                    item_rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
                except Exception:
                    continue
                if item_rid == rid:
                    return item
        return None

    def duplicate_item_ids(self, items: list[dict[str, Any]] | None = None) -> list[int]:
        """Return item-instance IDs whose player definition is already owned."""
        owned = self.owned_player_resource_ids()
        check = items if items is not None else self.list_items("unassigned")
        dupes: list[int] = []
        for item in check:
            try:
                rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
                iid = int(item.get("id", 0) or 0)
            except Exception:
                continue
            if rid in owned and iid:
                dupes.append(iid)
        return dupes

    def mark_item_duplicate(self, item_id: int, is_duplicate: bool = True) -> bool:
        """Persist only a conservative duplicate marker/pile state."""
        with self.lock:
            row = self.conn.execute("SELECT data FROM items WHERE id=?", (int(item_id),)).fetchone()
            if not row:
                return False
            try:
                data = json.loads(row[0])
            except Exception:
                return False
            # Do not inject UI-only symbols into the native FUT item schema.
            for key in ("IS_DUPLICATE", "isItemAlreadyInClub", "DUPLICATE_CARD_REF", "duplicateCardRef"):
                data.pop(key, None)
            data["duplicate"] = bool(is_duplicate)
            data["isDuplicate"] = bool(is_duplicate)
            if is_duplicate:
                data["pile"] = "unassigned"
            self.conn.execute("UPDATE items SET pile=?, data=? WHERE id=?",
                              (str(data.get("pile", "unassigned")), json.dumps(data), int(item_id)))
            self.conn.commit()
            return True

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        """Return one stored FUT item by item-instance id."""
        with self.lock:
            row = self.conn.execute("SELECT data FROM items WHERE id=?", (int(item_id),)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def would_duplicate_owned_player(self, item_id: int) -> bool:
        """True when moving this player into club/squad would duplicate a definition."""
        item = self.get_item(item_id)
        if not item or str(item.get("itemType", "player")) != "player":
            return False
        try:
            rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
        except Exception:
            return False
        if not rid:
            return False
        # Compare against cards already owned in club/squad. The item being moved
        # is normally still unassigned, so it is naturally excluded here.
        return rid in self.owned_player_resource_ids()


    def _normalize_existing_consumables(self) -> None:
        """Repair legacy consumables so native search/apply can classify them.

        Several earlier FIFA 15 builds stored cards that rendered visually but
        lacked category/consumableKind metadata. They consequently fell into the
        Training tab and were invisible to Apply Consumable's client cache.
        """
        repaired = 0
        rows = self.conn.execute("SELECT id,resource_id,pile,data FROM items ORDER BY id").fetchall()
        for row in rows:
            try:
                item = json.loads(row["data"])
            except Exception:
                continue
            if not isinstance(item, dict) or str(item.get("itemType", "player")) == "player":
                continue
            try:
                rid = int(item.get("resourceId", row["resource_id"]) or row["resource_id"])
            except Exception:
                rid = int(row["resource_id"] or 0)
            definition = CONSUMABLE_BY_RESOURCE.get(rid)
            if not definition:
                continue
            before = json.dumps(item, sort_keys=True, separators=(",", ":"))
            item["resourceId"] = rid
            item["assetId"] = rid
            item["resourceGameYear"] = 2015
            for key in (
                "cardassetid", "cardsubtypeid", "rating", "amount", "bronze",
                "silver", "gold", "weightrare", "category", "class", "kind",
                "quality", "applicationSupported", "sourceMember",
            ):
                if key in definition:
                    item[key] = definition[key]
            rare = int(definition.get("rareflag", definition.get("rareFlag", item.get("rareflag", 0))) or 0)
            item["rareflag"] = rare
            item["rareFlag"] = rare
            item["itemType"] = str(definition.get("itemType", item.get("itemType", "development")) or "development")
            family = _consumable_family_from_definition(definition)
            class_key = str(definition.get("class", "") or "").casefold()
            kind_key = str(definition.get("kind", "") or "")
            if family == "contracts":
                item["consumableKind"] = "contract_player"
                item["consumablesContractPlayer"] = 1
            elif family == "managercontracts":
                item["consumableKind"] = "contract_manager"
                item["consumablesContractManager"] = 1
            elif family == "fitness":
                item["consumableKind"] = "fitness_team" if kind_key.casefold() == "squad" else "fitness_player"
                if kind_key.casefold() == "squad":
                    item["consumablesFitnessTeam"] = int(definition.get("amount", 0) or 0)
                else:
                    item["consumablesFitnessPlayer"] = int(definition.get("amount", 0) or 0)
            elif family == "healing":
                item["consumableKind"] = "healing"
                item["consumablesHealing"] = int(definition.get("amount", 0) or 0)
            elif family == "training":
                item["consumableKind"] = "gk_training" if str(definition.get("category", "")).casefold() == "gk training" else "training_player"
                item["consumablesTrainingPlayer"] = int(definition.get("amount", 0) or 0)
            elif family == "position":
                item["consumableKind"] = "position_player"
            elif family == "playstyle":
                item["consumableKind"] = "playstyle_player"
            elif family == "managerleague":
                item["consumableKind"] = "managerleague_manager"
            item["displayName"] = str(
                item.get("displayName") or definition.get("displayName") or definition.get("name")
                or (str(definition.get("kind", "")) + " " + str(definition.get("category", "Consumable"))).strip()
            )
            after = json.dumps(item, sort_keys=True, separators=(",", ":"))
            if after != before:
                self.conn.execute(
                    "UPDATE items SET resource_id=?,data=? WHERE id=?",
                    (rid, json.dumps(item), int(row["id"])),
                )
                repaired += 1
        if repaired:
            self.conn.commit()
            log.warning("CONSUMABLE MIGRATION repaired %s persisted item(s)", repaired)

    def owned_consumable_item(self, resource_id: int) -> dict[str, Any] | None:
        rid = int(resource_id)
        for item in self.list_items("club"):
            if str(item.get("itemType", "player")) == "player":
                continue
            try:
                if int(item.get("resourceId", 0) or 0) == rid:
                    return item
            except Exception:
                continue
        return None

    def active_squad_player_ids(self) -> list[int]:
        squads = self.list_squads()
        active = next((x for x in squads if bool(x.get("active", False))), squads[0] if squads else {})
        ids: list[int] = []
        for entry in active.get("players", []) if isinstance(active, dict) else []:
            if not isinstance(entry, dict):
                continue
            try:
                iid = int(entry.get("itemId", 0) or 0)
            except Exception:
                iid = 0
            if iid > 0 and iid not in ids:
                ids.append(iid)
        return ids

    def apply_consumable(self, resource_id: int, target_item_ids: list[int]) -> dict[str, Any]:
        """Consume one owned card and persist its effect on player/manager state."""
        rid = int(resource_id)
        definition = CONSUMABLE_BY_RESOURCE.get(rid)
        if not definition:
            raise ValueError(f"unknown consumable resourceId {rid}")
        if definition.get("applicationSupported") is False:
            raise ValueError(f"consumable resourceId {rid} is not application-supported")
        owned = self.owned_consumable_item(rid)
        if not owned:
            raise ValueError(f"consumable resourceId {rid} is not owned")
        targets: list[int] = []
        for value in target_item_ids:
            try:
                iid = int(value)
            except Exception:
                continue
            if iid > 0 and iid not in targets:
                targets.append(iid)
        if not targets:
            raise ValueError("consumable application requires a target item id")

        family = _consumable_family_from_definition(definition)
        amount = max(0, int(definition.get("amount", 0) or 0))
        changed: list[dict[str, Any]] = []

        def load_target(iid: int) -> dict[str, Any]:
            item = self.get_item(iid)
            if not item:
                raise ValueError(f"target item {iid} is not owned")
            return item

        def save_target(item: dict[str, Any]) -> None:
            iid = int(item.get("id", 0) or 0)
            pile = str(item.get("pile", "club") or "club")
            with self.lock:
                self.conn.execute(
                    "UPDATE items SET pile=?,data=? WHERE id=?",
                    (pile, json.dumps(item), iid),
                )
                self.conn.commit()
            changed.append(item)

        if family == "fitness" and str(definition.get("kind", "")).casefold() == "squad":
            for iid in self.active_squad_player_ids():
                item = load_target(iid)
                if str(item.get("itemType", "player")) != "player":
                    continue
                item["fitness"] = min(99, max(0, int(item.get("fitness", 0) or 0)) + amount)
                save_target(item)
            effect = f"squad fitness +{amount}"
        elif family in {"contracts", "fitness", "healing", "training", "position", "playstyle"}:
            item = load_target(targets[0])
            if str(item.get("itemType", "player")) != "player":
                raise ValueError("consumable target is not an owned player")
            if family == "contracts":
                rating = int(item.get("rating", 75) or 75)
                quality = "bronze" if rating <= 64 else "silver" if rating <= 74 else "gold"
                gain = max(0, int(definition.get(quality, amount) or 0))
                item["contract"] = min(99, max(0, int(item.get("contract", item.get("contracts", 0)) or 0)) + gain)
                item["contracts"] = item["contract"]
                effect = f"player contract +{gain}"
            elif family == "fitness":
                item["fitness"] = min(99, max(0, int(item.get("fitness", 0) or 0)) + amount)
                effect = f"player fitness +{amount}"
            elif family == "healing":
                item["injuryGames"] = max(0, int(item.get("injuryGames", 0) or 0) - max(1, amount))
                if int(item.get("injuryGames", 0) or 0) == 0:
                    item["injuryType"] = "none"
                effect = f"healing {max(1, amount)}"
            elif family == "training":
                # Training cards are temporary face-stat boosts, not a generic
                # integer counter.  v0.2.19 consumed the card but only changed
                # `training`, so FIFA had no visible attribute mutation to show.
                category = str(definition.get("category", "Training") or "Training")
                kind = str(definition.get("kind", "ALL") or "ALL").upper()
                position = str(item.get("preferredPosition", "") or "").upper()
                is_gk = position == "GK"
                if category.casefold() == "gk training" and not is_gk:
                    raise ValueError("goalkeeper training requires a goalkeeper")
                if category.casefold() == "training" and is_gk:
                    raise ValueError("outfield training cannot be applied to a goalkeeper")
                # Training does not permanently rewrite the card. If a player
                # already has a training effect, a new card replaces that effect
                # from the original base attributes rather than stacking forever.
                base_rows = item.get("trainingBaseAttributeList") if isinstance(item.get("trainingBaseAttributeList"), list) else item.get("attributeList", [])
                attrs = [0] * 6
                for row in base_rows if isinstance(base_rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    try:
                        idx = int(row.get("index", -1))
                        val = int(row.get("value", 0) or 0)
                    except Exception:
                        continue
                    if 0 <= idx < 6:
                        attrs[idx] = val
                if not any(attrs):
                    attrs = [int(x.get("value", 0) or 0) for x in player_attribute_list(int(item.get("resourceId", 0) or 0))][:6]
                    attrs += [0] * (6 - len(attrs))
                item["trainingBaseAttributeList"] = [{"index": i, "value": int(v)} for i, v in enumerate(attrs)]
                index_map = ({"DIV":0,"HAN":1,"KIC":2,"REF":3,"SPD":4,"POS":5}
                             if is_gk else {"PAC":0,"SHO":1,"PAS":2,"DRI":3,"DEF":4,"PHY":5,"HEA":5})
                if kind == "ALL":
                    indexes = range(6)
                elif kind in index_map:
                    indexes = (index_map[kind],)
                else:
                    raise ValueError(f"unsupported training subtype {kind}")
                for idx in indexes:
                    attrs[idx] = min(99, max(0, int(attrs[idx])) + amount)
                item["attributeList"] = [{"index": i, "value": int(v)} for i, v in enumerate(attrs)]
                # `training` is the retail-era player ItemData flag used by the
                # client to mark a card as temporarily trained. Keep the resource
                # id as an explicit local alias for diagnostics/restarts.
                item["training"] = max(1, int(definition.get("cardsubtypeid", 1) or 1))
                item["trainingResourceId"] = int(resource_id)
                item["trainingExpiresAfterMatch"] = 1
                effect = f"{category.lower()} {kind} +{amount} for next match"
            elif family == "position":
                move = str(definition.get("kind", "") or "")
                if "→" in move:
                    source, dest = [x.strip().upper() for x in move.split("→", 1)]
                elif "->" in move:
                    source, dest = [x.strip().upper() for x in move.split("->", 1)]
                else:
                    source, dest = "", ""
                current = str(item.get("preferredPosition", "") or "").upper()
                if source and current and current != source:
                    raise ValueError(f"position card expects {source}, target is {current}")
                if dest:
                    item["preferredPosition"] = dest
                effect = f"position {source}->{dest}"
            else:
                item["playStyle"] = int(definition.get("amount", 0) or 0)
                effect = f"playStyle {item['playStyle']}"
            save_target(item)
        elif family in {"managercontracts", "managerleague"}:
            item = load_target(targets[0])
            if str(item.get("itemType", "")).lower() not in {"manager", "staff"}:
                raise ValueError("manager consumable target is not an owned manager")
            if family == "managercontracts":
                rating = int(item.get("rating", 75) or 75)
                quality = "bronze" if rating <= 64 else "silver" if rating <= 74 else "gold"
                gain = max(0, int(definition.get(quality, amount) or 0))
                item["contract"] = min(99, max(0, int(item.get("contract", 0) or 0)) + gain)
                effect = f"manager contract +{gain}"
            else:
                item["leagueId"] = amount
                effect = f"manager league {amount}"
            save_target(item)
        else:
            raise ValueError(f"unsupported consumable family {family}")

        consumed_id = int(owned.get("id", 0) or 0)
        if consumed_id:
            self.delete_item(consumed_id)
        log.warning(
            "CONSUMABLE APPLY resource=%s family=%s target=%s consumedItem=%s effect=%s",
            rid, family, targets, consumed_id, effect,
        )
        return {"consumedItemId": consumed_id, "effect": effect, "itemData": changed}

    def _seed_squad(self) -> None:
        players = self.list_items("club")[:11]
        lineup = []
        for idx, item in enumerate(players):
            lineup.append({"index": idx, "itemId": item["id"], "loyaltyBonus": 1})
        squad = {
            "id": 1,
            "squadId": 1,
            "name": "Local XI",
            "squadName": "Local XI",
            "formation": "f442",
            "rating": 0,
            "chemistry": 0,
            "active": True,
            "players": lineup,
            "kicktakers": [],
        }
        with self.lock:
            self.conn.execute(
                "INSERT INTO squads(id,name,active,data) VALUES(1,?,?,?)",
                ("Local XI", 1, json.dumps(squad)),
            )
            self.conn.commit()

    def list_squads(self) -> list[dict[str, Any]]:
        # SQL active is canonical. Older saved JSON can still contain active=true
        # after another squad was selected, so always overlay the table flag.
        with self.lock:
            rows = self.conn.execute("SELECT id,name,active,data FROM squads ORDER BY active DESC,id").fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                doc = json.loads(r["data"])
            except Exception:
                doc = {}
            if not isinstance(doc, dict):
                doc = {}
            doc["id"] = int(r["id"])
            doc["squadId"] = int(r["id"])
            doc["name"] = str(doc.get("name") or r["name"] or f"Squad {int(r['id'])}")
            doc["squadName"] = str(doc.get("squadName") or doc["name"])
            doc["active"] = bool(r["active"])
            out.append(doc)
        return out

    def _resolve_owned_item_id(self, raw: Any) -> int | None:
        """Resolve a squad slot reference without inventing a new item instance."""
        try:
            value = int(raw or 0)
        except Exception:
            return None
        if value <= 0:
            return None
        row = self.conn.execute("SELECT id FROM items WHERE id=?", (value,)).fetchone()
        if row:
            return int(row[0])
        # Some native squad writes fall back to asset/resource ids rather than the
        # item-instance id. Prefer an already owned copy, never an unassigned one.
        rows = self.conn.execute(
            "SELECT id,data FROM items WHERE resource_id=? AND pile IN ('club','squad') ORDER BY id",
            (value,),
        ).fetchall()
        if rows:
            return int(rows[0][0])
        for row in self.conn.execute("SELECT id,data FROM items WHERE pile IN ('club','squad') ORDER BY id").fetchall():
            try:
                data = json.loads(row[1])
                if int(data.get("assetId", 0) or 0) == value:
                    return int(row[0])
            except Exception:
                continue
        return None

    def _sync_squad_item_piles_locked(self) -> None:
        """Make item pile state match membership across every locally saved squad."""
        member_ids: set[int] = set()
        for row in self.conn.execute("SELECT data FROM squads").fetchall():
            try:
                doc = json.loads(row[0])
            except Exception:
                continue
            players = doc.get("players", []) if isinstance(doc, dict) else []
            if not isinstance(players, list):
                continue
            for entry in players:
                if not isinstance(entry, dict):
                    continue
                raw = entry.get("itemId")
                if raw is None and isinstance(entry.get("itemData"), dict):
                    raw = entry["itemData"].get("id") or entry["itemData"].get("itemId")
                try:
                    iid = int(raw or 0)
                except Exception:
                    iid = 0
                if iid > 0:
                    member_ids.add(iid)

        rows = self.conn.execute("SELECT id,pile,data FROM items").fetchall()
        for row in rows:
            try:
                data = json.loads(row["data"])
            except Exception:
                continue
            if str(data.get("itemType", "player")) != "player":
                continue
            current = str(row["pile"])
            if current in ("trade", "unassigned", "pending"):
                continue
            wanted = "squad" if int(row["id"]) in member_ids else "club"
            if current != wanted or str(data.get("pile", current)) != wanted:
                data["pile"] = wanted
                self.conn.execute(
                    "UPDATE items SET pile=?,data=? WHERE id=?",
                    (wanted, json.dumps(data), int(row["id"])),
                )

    def save_squad(self, payload: Any) -> dict[str, Any]:
        """Persist FIFA 15 squad writes without letting sparse updates erase the XI.

        FIFA sends a mixture of full 23-slot documents and smaller metadata/slot
        updates. Older builds replaced the whole stored JSON on every PUT, so one
        partial write could wipe the lineup and it disappeared after relaunch.
        """
        src = dict(payload) if isinstance(payload, dict) else {}
        if isinstance(src.get("squad"), dict):
            src = dict(src["squad"])
        sid = int(src.get("id") or src.get("squadId") or 1)

        with self.lock:
            row = self.conn.execute("SELECT name,active,data FROM squads WHERE id=?", (sid,)).fetchone()
            if row:
                try:
                    existing = json.loads(row["data"])
                except Exception:
                    existing = {}
            else:
                existing = {
                    "id": sid, "squadId": sid, "name": f"Squad {sid}",
                    "squadName": f"Squad {sid}", "formation": "f442",
                    "active": sid == 1, "players": [], "kicktakers": [],
                }

            merged = dict(existing) if isinstance(existing, dict) else {}
            # Metadata writes are incremental. Preserve anything FIFA omitted.
            for key, value in src.items():
                if key != "players":
                    merged[key] = value

            incoming_players = src.get("players")
            existing_players = existing.get("players", []) if isinstance(existing, dict) else []
            slot_map: dict[int, dict[str, Any]] = {}
            if isinstance(existing_players, list):
                for entry in existing_players:
                    if not isinstance(entry, dict):
                        continue
                    try:
                        idx = int(entry.get("index", -1))
                    except Exception:
                        continue
                    if 0 <= idx < 23:
                        slot_map[idx] = dict(entry)

            if isinstance(incoming_players, list):
                valid_entries = 0
                explicit_slots: set[int] = set()
                for entry in incoming_players:
                    if not isinstance(entry, dict):
                        continue
                    try:
                        idx = int(entry.get("index", -1))
                    except Exception:
                        continue
                    if not 0 <= idx < 23:
                        continue
                    explicit_slots.add(idx)
                    raw = entry.get("itemId")
                    if raw is None and isinstance(entry.get("itemData"), dict):
                        raw = (entry["itemData"].get("id") or entry["itemData"].get("itemId")
                               or entry["itemData"].get("resourceId") or entry["itemData"].get("assetId"))
                    resolved = self._resolve_owned_item_id(raw)
                    # An explicit empty slot is meaningful; preserve its index.
                    normalized: dict[str, Any] = {"index": idx, "kitNumber": int(entry.get("kitNumber", 0) or 0)}
                    if resolved:
                        normalized["itemId"] = resolved
                        valid_entries += 1
                    slot_map[idx] = normalized

                existing_nonempty = sum(1 for e in slot_map.values() if int(e.get("itemId", 0) or 0) > 0)
                # Full retail documents contain most/all 23 slots. For sparse writes,
                # only touch the explicitly supplied indexes and retain the rest.
                # If the parser somehow recognized almost nothing while a complete
                # XI already exists, keep the old membership rather than corrupt it.
                if len(incoming_players) >= 11 or valid_entries >= 7 or existing_nonempty < 7:
                    pass
                elif valid_entries == 0 and existing_nonempty >= 7:
                    log.warning(
                        "SQUAD SAVE protected existing XI from sparse/unresolved write sid=%s entries=%s",
                        sid, len(incoming_players),
                    )
                    slot_map = {}
                    for entry in existing_players if isinstance(existing_players, list) else []:
                        if isinstance(entry, dict):
                            try:
                                idx = int(entry.get("index", -1))
                            except Exception:
                                continue
                            if 0 <= idx < 23:
                                slot_map[idx] = dict(entry)

                merged["players"] = [slot_map[i] for i in sorted(slot_map)]

            # Explicit rename/create fields win over the previously persisted aliases.
            name = str(src.get("squadName") or src.get("name") or merged.get("squadName") or merged.get("name") or f"Squad {sid}")
            merged["id"] = sid
            merged["squadId"] = sid
            merged["name"] = name
            merged["squadName"] = name
            active = 1 if bool(merged.get("active", row["active"] if row else sid == 1)) else 0
            merged["active"] = bool(active)

            if active:
                self.conn.execute("UPDATE squads SET active=0")
            self.conn.execute(
                "INSERT INTO squads(id,name,active,data) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,active=excluded.active,data=excluded.data",
                (sid, name, active, json.dumps(merged)),
            )
            self._sync_squad_item_piles_locked()
            self.conn.commit()

        count = sum(1 for x in merged.get("players", []) if isinstance(x, dict) and int(x.get("itemId", 0) or 0) > 0)
        log.warning("SQUAD SAVE persisted sid=%s active=%s players=%s formation=%s", sid, bool(active), count, merged.get("formation"))
        return merged

    def next_squad_id(self) -> int:
        with self.lock:
            row = self.conn.execute("SELECT COALESCE(MAX(id),0) FROM squads").fetchone()
            return max(1, int(row[0] if row else 0) + 1)

    def create_squad(self, payload: Any) -> dict[str, Any]:
        src = dict(payload) if isinstance(payload, dict) else {}
        sid = self.next_squad_id()
        src["id"] = sid
        src["squadId"] = sid
        src["active"] = True
        src.setdefault("squadName", src.get("name") or f"Squad {sid}")
        src.setdefault("name", src.get("squadName") or f"Squad {sid}")
        src.setdefault("formation", "f442")
        src.setdefault("players", [])
        saved = self.save_squad(src)
        log.warning("SQUAD CREATE sid=%s name=%s players=%s", sid, saved.get("squadName"), len(saved.get("players", [])))
        return saved

    def clone_squad(self, source_id: int, name: str | None = None) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT data FROM squads WHERE id=?", (int(source_id),)).fetchone()
        if not row:
            return None
        try:
            src = json.loads(row[0])
        except Exception:
            return None
        src = dict(src) if isinstance(src, dict) else {}
        src.pop("id", None)
        src.pop("squadId", None)
        if name:
            src["name"] = str(name)[:32]
            src["squadName"] = str(name)[:32]
        return self.create_squad(src)

    def delete_squad(self, sid: int) -> bool:
        sid = int(sid)
        with self.lock:
            rows = self.conn.execute("SELECT id,active FROM squads ORDER BY id").fetchall()
            if len(rows) <= 1:
                return False
            cur = self.conn.execute("DELETE FROM squads WHERE id=?", (sid,))
            if not cur.rowcount:
                self.conn.commit()
                return False
            active = self.conn.execute("SELECT id FROM squads WHERE active=1 ORDER BY id LIMIT 1").fetchone()
            if active is None:
                fallback = self.conn.execute("SELECT id FROM squads ORDER BY id LIMIT 1").fetchone()
                if fallback:
                    self.conn.execute("UPDATE squads SET active=0")
                    self.conn.execute("UPDATE squads SET active=1 WHERE id=?", (int(fallback[0]),))
                    row = self.conn.execute("SELECT data FROM squads WHERE id=?", (int(fallback[0]),)).fetchone()
                    if row:
                        try:
                            doc = json.loads(row[0]); doc["active"] = True
                            self.conn.execute("UPDATE squads SET data=? WHERE id=?", (json.dumps(doc), int(fallback[0])))
                        except Exception:
                            pass
            self._sync_squad_item_piles_locked()
            self.conn.commit()
            return True

    def next_trade_id(self) -> int:
        with self.lock:
            v = int(self.get("next_trade_id", 650000000000)) + 1
            self.set("next_trade_id", v)
            return v

    def market_reference_price(self, resource_id: int) -> int:
        """Deterministic local guide price based on FIFA 15 card quality/rarity."""
        meta = player_meta(int(resource_id))
        rating = int(meta.get("rating", 60) or 60)
        rareflag = int(meta.get("rareflag", 0) or 0)
        tier = str(meta.get("tier", "") or "").lower()
        if not tier:
            tier = "gold" if rating >= 75 else "silver" if rating >= 65 else "bronze"

        if tier == "bronze":
            base = 150 + max(0, rating - 45) * 22
        elif tier == "silver":
            base = 300 + max(0, rating - 65) ** 2 * 65 + max(0, rating - 65) * 80
        else:
            if rating <= 78:
                base = 650 + max(0, rating - 75) * 275
            elif rating <= 82:
                base = 1800 + (rating - 79) * 1500
            elif rating <= 85:
                base = 8000 + (rating - 83) * 7500
            elif rating <= 88:
                base = 35000 + (rating - 86) * 35000
            elif rating <= 90:
                base = 150000 + (rating - 89) * 125000
            else:
                base = 450000 + (rating - 91) * 300000

        if rareflag == 1:
            base *= 1.18
        elif rareflag > 1:
            multipliers = {3: 1.9, 4: 2.2, 5: 4.5, 6: 3.0, 7: 2.0, 8: 2.7, 9: 2.4, 11: 3.6}
            base *= multipliers.get(rareflag, 2.2)
            # Never generate a special-card market guide below quick-sell.
            # A 15% margin stops low-rated IFs appearing for ~3k while their
            # discard value is 10k-14k.
            base = max(base, self.player_discard_value(int(resource_id)) * 1.15)

        # FUT prices are naturally rounded to common step sizes.
        price = int(max(150, min(15000000, base)))
        if price < 1000:
            step = 50
        elif price < 10000:
            step = 100
        elif price < 50000:
            step = 250
        elif price < 100000:
            step = 500
        else:
            step = 1000
        return max(150, int(round(price / step) * step))

    def create_user_auction(self, item_id: int, starting_bid: int, buy_now: int, duration: int) -> dict[str, Any] | None:
        item = self.get_item(int(item_id))
        if not item or str(item.get("pile", "club")) == "squad":
            return None
        current_pile = str(item.get("pile", "club") or "club")
        if current_pile not in ("trade", "tradepile") and self.transfer_list_count() >= 100:
            log.warning("TRANSFER LIST listing rejected item=%s: pile full", item_id)
            return None

        rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
        if not rid:
            return None
        if bool(item.get("untradeable", False)):
            log.warning("AI MARKET listing rejected item=%s rid=%s: untradeable", item_id, rid)
            return None

        existing = self.user_auction_for_item(int(item_id))
        existing_state = str(existing.get("state", "")) if existing else ""
        if existing and existing_state == "active":
            # FIFA can retry POST /auctionhouse during a UI transition.  An
            # already-live auction is idempotent and should not duplicate.
            return existing
        if existing and existing_state == "sold":
            # A completed sale cannot be relisted. The sold row is cleared by
            # the normal Transfer List sold-item removal path.
            return existing

        starting_bid = max(150, int(starting_bid or 150))
        buy_now = max(starting_bid, int(buy_now or starting_bid))
        duration = max(60, int(duration or 3600))
        trade_id = self.next_trade_id()
        created = now_s()
        expires = created + duration

        market_value = self.market_reference_price(rid)
        copies = max(1, min(10, int(CFG.get("ai_market_copies_per_card", 10) or 10)))
        try:
            cheapest = min(_market_price_for_resource(rid, slot)[1] for slot in range(copies))
        except Exception:
            cheapest = market_value

        if buy_now <= cheapest:
            base_delay, span = 18, 28
        elif buy_now <= market_value:
            base_delay, span = 40, 55
        elif buy_now <= int(market_value * 1.10):
            base_delay, span = 75, 100
        else:
            base_delay, span = 0, 0

        auto_sell_after = 0
        if base_delay:
            deterministic = (trade_id * 1103515245 + rid * 12345) & 0x7FFFFFFF
            auto_sell_after = base_delay + deterministic % span

        # Persist the exact transfer-list item state before returning the auction.
        item = dict(item)
        item["pile"] = "trade"
        item["itemState"] = "forSale"
        item["untradeable"] = False
        item["tradeable"] = True
        item_payload_json = json.dumps(item, separators=(",", ":"), ensure_ascii=False)
        data = {
            "sellerName": str(self.get("persona_name", CFG.get("display_name", "LocalPlayer"))),
            "marketValue": int(market_value),
            "cheapestMarketPrice": int(cheapest),
        }

        with self.lock:
            self.conn.execute(
                "UPDATE items SET pile='trade',data=? WHERE id=?",
                (item_payload_json, int(item_id)),
            )
            if existing and existing_state == "expired":
                # Individual relist from an expired Transfer List card comes back
                # through POST /auctionhouse with the same owned item id.  Older
                # builds returned the expired row unchanged, so FIFA accepted the
                # POST but the card immediately remained Expired. Reactivate the
                # existing trade in-place so the client's selected trade identity
                # stays coherent while prices/duration and AI-sale timing reset.
                trade_id = int(existing.get("trade_id", trade_id) or trade_id)
                self.conn.execute(
                    "UPDATE auctions SET starting_bid=?,buy_now=?,current_bid=0,"
                    "created=?,expires=?,state='active',credited=0,data=?,sold_price=0,"
                    "sold_at=0,auto_sell_after=?,market_value_at_list=?,item_payload=? "
                    "WHERE trade_id=?",
                    (
                        starting_bid, buy_now, created, expires, json.dumps(data),
                        int(auto_sell_after), int(market_value), item_payload_json, trade_id,
                    ),
                )
                action = "RELISTED"
            else:
                self.conn.execute(
                    "INSERT INTO auctions("
                    "trade_id,item_id,resource_id,seller_is_user,starting_bid,buy_now,current_bid,"
                    "created,expires,state,credited,data,sold_price,sold_at,auto_sell_after,"
                    "market_value_at_list,item_payload"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        trade_id, int(item_id), rid, 1, starting_bid, buy_now, 0,
                        created, expires, "active", 0, json.dumps(data), 0, 0,
                        int(auto_sell_after), int(market_value), item_payload_json,
                    ),
                )
                action = "LISTED"
            self.conn.commit()

        log.warning(
            "AI MARKET %s trade=%s item=%s rid=%s start=%s bin=%s market=%s cheapest=%s autoSell=%ss",
            action, trade_id, item_id, rid, starting_bid, buy_now, market_value, cheapest, auto_sell_after,
        )
        return self.user_auction(trade_id)

    def ensure_transfer_action_bridge(self, item_id: int) -> dict[str, Any] | None:
        """Give an unlisted Transfer List item a selectable expired trade shell.

        FIFA 15 PC renders pile=5/tradeId=0 correctly as "not currently listed",
        but the native Transfer List controller never dispatches the Enter/A list
        action for that zero-id row.  The same controller *does* allow an expired
        owner auction to be opened and edited.  Use a persistent expired shell as
        an interaction bridge; POST /auctionhouse then reactivates this exact row.
        """
        existing = self.user_auction_for_item(int(item_id))
        if existing:
            return existing
        item = self.get_item(int(item_id))
        if not item or str(item.get("pile", "")) not in ("trade", "tradepile"):
            return None
        if bool(item.get("untradeable", False)):
            return None
        rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
        if not rid:
            return None
        guide = max(150, int(self.market_reference_price(rid)))
        # Sensible expired defaults only seed the price editor; the user's final
        # values arrive via POST /auctionhouse and replace them.
        start = max(150, int(round((guide * 0.65) / 50.0) * 50))
        buy_now = max(start, int(round(guide / 50.0) * 50))
        trade_id = self.next_trade_id()
        now = now_s()
        item_copy = dict(item)
        item_copy.update({"pile": "trade", "itemState": "free", "untradeable": False, "tradeable": True})
        item_json = json.dumps(item_copy, separators=(",", ":"), ensure_ascii=False)
        meta = {"sellerName": str(self.get("persona_name", CFG.get("display_name", "LocalPlayer"))), "actionBridge": True}
        with self.lock:
            self.conn.execute(
                "INSERT INTO auctions("
                "trade_id,item_id,resource_id,seller_is_user,starting_bid,buy_now,current_bid,"
                "created,expires,state,credited,data,sold_price,sold_at,auto_sell_after,"
                "market_value_at_list,item_payload"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    trade_id, int(item_id), rid, 1, start, buy_now, 0,
                    now - 3600, now - 1, "expired", 0, json.dumps(meta), 0, 0,
                    0, guide, item_json,
                ),
            )
            self.conn.commit()
        log.warning(
            "TRANSFER LIST ACTION BRIDGE created trade=%s item=%s rid=%s start=%s bin=%s",
            trade_id, item_id, rid, start, buy_now,
        )
        return self.user_auction(trade_id)

    def user_auction(self, trade_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM auctions WHERE trade_id=?", (int(trade_id),)).fetchone()
        return dict(row) if row else None

    def list_user_auctions(self) -> list[dict[str, Any]]:
        # Repair ghosts left by older builds where quick-sell deleted items but
        # retained auctions.item_payload, causing /tradePile to resurrect them.
        with self.lock:
            orphans = self.conn.execute(
                "SELECT trade_id,item_id,state FROM auctions WHERE seller_is_user=1 "
                "AND item_id NOT IN (SELECT id FROM items)"
            ).fetchall()
            if orphans:
                self.conn.execute(
                    "DELETE FROM auctions WHERE seller_is_user=1 "
                    "AND item_id NOT IN (SELECT id FROM items)"
                )
                self.conn.commit()
                log.warning(
                    "TRANSFER LIST repaired orphan auctions=%s",
                    [(int(r["trade_id"]), int(r["item_id"]), str(r["state"])) for r in orphans],
                )
        self.simulate_ai_sales()
        with self.lock:
            rows = self.conn.execute("SELECT * FROM auctions WHERE seller_is_user=1 ORDER BY trade_id DESC").fetchall()
        return [dict(r) for r in rows]

    def simulate_ai_sales(self) -> None:
        """Lazy local buyers purchase competitively priced Transfer List cards."""
        if not bool(CFG.get("ai_market_enabled", True)):
            return
        now = now_s()
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM auctions WHERE seller_is_user=1 AND state='active' ORDER BY created,trade_id"
            ).fetchall()
            for row in rows:
                trade_id = int(row["trade_id"])
                rid = int(row["resource_id"])
                ask = int(row["buy_now"] or 0)
                created = int(row["created"] or now)
                expires = int(row["expires"] or (created + 3600))
                market_value = int(row["market_value_at_list"] or 0) or self.market_reference_price(rid)
                max_liquid_price = int(market_value * 1.10)
                sellable = ask > 0 and ask <= max_liquid_price

                auto_after = int(row["auto_sell_after"] or 0)
                if sellable and auto_after <= 0:
                    copies = max(1, min(10, int(CFG.get("ai_market_copies_per_card", 10) or 10)))
                    try:
                        cheapest = min(_market_price_for_resource(rid, slot)[1] for slot in range(copies))
                    except Exception:
                        cheapest = market_value
                    if ask <= cheapest:
                        base_delay, span = 18, 28
                    elif ask <= market_value:
                        base_delay, span = 40, 55
                    else:
                        base_delay, span = 75, 100
                    deterministic = (trade_id * 1103515245 + rid * 12345) & 0x7FFFFFFF
                    auto_after = base_delay + deterministic % span
                    self.conn.execute(
                        "UPDATE auctions SET auto_sell_after=?,market_value_at_list=? WHERE trade_id=?",
                        (int(auto_after), int(market_value), trade_id),
                    )

                if sellable and now >= created + auto_after:
                    sold_price = ask
                    credited = int(row["credited"] or 0)
                    if not credited:
                        current = int(self.get("credits", 0) or 0)
                        payout = max(0, int(round(sold_price * 0.95)))
                        self.conn.execute(
                            "INSERT INTO kv(key,value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            ("credits", json.dumps(max(0, current + payout))),
                        )
                        credited = 1
                    item_row = self.conn.execute(
                        "SELECT data FROM items WHERE id=?", (int(row["item_id"]),)
                    ).fetchone()
                    try:
                        item_payload = json.loads(item_row[0]) if item_row else json.loads(row["item_payload"] or "{}")
                    except Exception:
                        item_payload = {}
                    if not isinstance(item_payload, dict):
                        item_payload = {}
                    item_payload.update({
                        "pile": "trade",
                        "itemState": "sold",
                        "lastSalePrice": sold_price,
                        "untradeable": False,
                        "tradeable": True,
                    })
                    item_payload_json = json.dumps(item_payload, separators=(",", ":"), ensure_ascii=False)
                    self.conn.execute(
                        "UPDATE items SET pile='trade',data=? WHERE id=?",
                        (item_payload_json, int(row["item_id"])),
                    )
                    self.conn.execute(
                        "UPDATE auctions SET state='sold',credited=?,sold_price=?,sold_at=?,"
                        "current_bid=?,item_payload=? WHERE trade_id=?",
                        (
                            credited, sold_price, now, sold_price,
                            item_payload_json, trade_id,
                        ),
                    )
                    log.warning(
                        "AI MARKET SOLD trade=%s item=%s rid=%s price=%s tax=%s net=%s",
                        trade_id, int(row["item_id"]), rid, sold_price,
                        sold_price - max(0, int(round(sold_price * 0.95))),
                        max(0, int(round(sold_price * 0.95))),
                    )
                    continue

                if now >= expires:
                    # Overpriced/unsold cards expire but remain on the Transfer List.
                    self.conn.execute(
                        "UPDATE auctions SET state='expired' WHERE trade_id=?",
                        (trade_id,),
                    )
                    item_row = self.conn.execute(
                        "SELECT data FROM items WHERE id=?", (int(row["item_id"]),)
                    ).fetchone()
                    if item_row:
                        try:
                            item_payload = json.loads(item_row[0])
                        except Exception:
                            item_payload = {}
                        if isinstance(item_payload, dict):
                            item_payload.update({
                                "pile": "trade", "itemState": "free",
                                "untradeable": False, "tradeable": True,
                            })
                            self.conn.execute(
                                "UPDATE items SET pile='trade',data=? WHERE id=?",
                                (json.dumps(item_payload, separators=(",", ":"), ensure_ascii=False),
                                 int(row["item_id"])),
                            )
                    log.info("AI MARKET EXPIRED trade=%s item=%s rid=%s ask=%s", trade_id, int(row["item_id"]), rid, ask)

            self.conn.commit()

    def delete_user_auction(self, trade_id: int, return_item: bool = True) -> bool:
        row = self.user_auction(int(trade_id))
        if not row:
            return False
        item_id = int(row.get("item_id", 0) or 0)
        state = str(row.get("state", "active"))
        with self.lock:
            cur = self.conn.execute("DELETE FROM auctions WHERE trade_id=?", (int(trade_id),))
            self.conn.commit()
        if return_item and item_id and state != "sold":
            self.update_item_pile(item_id, "club")
        elif item_id and state == "sold":
            self.delete_item(item_id)
        return bool(cur.rowcount)

    def offline_season_state(self) -> dict[str, int]:
        return {
            "division": int(self.get("offline_season_division", 10)),
            "points": int(self.get("offline_season_points", 0)),
            "round": int(self.get("offline_season_round", 0)),
            "wins": int(self.get("offline_season_wins", 0)),
            "draws": int(self.get("offline_season_draws", 0)),
            "losses": int(self.get("offline_season_losses", 0)),
            "goalsFor": int(self.get("offline_season_goals_for", 0)),
            "goalsAgainst": int(self.get("offline_season_goals_against", 0)),
            "trophies": int(self.get("offline_season_trophies", 0)),
        }

    def update_offline_season(self, payload: dict[str, Any]) -> dict[str, int]:
        state = self.offline_season_state()
        # Accept native-ish progress payloads without requiring a single schema.
        for src, key in (("round", "round"), ("points", "points"), ("wins", "wins"), ("draws", "draws"),
                         ("losses", "losses"), ("goalsFor", "goalsFor"), ("goalsAgainst", "goalsAgainst")):
            if src in payload:
                try: state[key] = max(0, int(payload[src]))
                except Exception: pass
        result = str(payload.get("result", "") or "").lower()
        if result in ("win", "w"):
            state["wins"] += 1; state["points"] += 3; state["round"] += 1
        elif result in ("draw", "d"):
            state["draws"] += 1; state["points"] += 1; state["round"] += 1
        elif result in ("loss", "lose", "l"):
            state["losses"] += 1; state["round"] += 1
        mapping = {
            "offline_season_division": state["division"], "offline_season_points": state["points"],
            "offline_season_round": state["round"], "offline_season_wins": state["wins"],
            "offline_season_draws": state["draws"], "offline_season_losses": state["losses"],
            "offline_season_goals_for": state["goalsFor"], "offline_season_goals_against": state["goalsAgainst"],
        }
        for k, v in mapping.items(): self.set(k, v)
        return self.offline_season_state()

    def reset_offline_season(self, division: int | None = None) -> dict[str, int]:
        if division is not None:
            self.set("offline_season_division", max(1, min(10, int(division))))
        for key in ("offline_season_points", "offline_season_round", "offline_season_wins", "offline_season_draws",
                    "offline_season_losses", "offline_season_goals_for", "offline_season_goals_against"):
            self.set(key, 0)
        self.set("offline_season_active", False)
        self.set("offline_season_wire_round", 1)
        self.set("offline_season_wire_data", "")
        self.set("offline_season_wire_progress_data", "")
        return self.offline_season_state()

    def create_pack(self, pack_id: int = 1) -> dict[str, Any]:
        cleared = self.clear_pile("unassigned")
        if cleared:
            log.info("Cleared %d stale unassigned item(s) before new pack", cleared)

        pcfg = get_pack_cfg(pack_id)
        if not pcfg:
            raise RuntimeError(f"Unknown pack id {pack_id}")

        pack_size = max(1, min(30, int(pcfg.get("size", 12))))
        player_slots = max(0, min(pack_size, int(pcfg.get("player_slots", pack_size))))
        club_item_slots = max(0, min(pack_size - player_slots, int(pcfg.get("club_item_slots", 0) or 0)))
        misc_slots = pack_size - player_slots - club_item_slots
        rare_slots = max(0, min(pack_size, int(pcfg.get("rare_slots", 3))))
        player_rare_slots = max(0, min(player_slots, int(pcfg.get("player_rare_slots", min(rare_slots, player_slots)))))
        club_rare_slots = max(0, min(club_item_slots, rare_slots - player_rare_slots))
        misc_rare_slots = max(0, min(misc_slots, rare_slots - player_rare_slots - club_rare_slots))
        special_chance = max(0.0, min(1.0, float(pcfg.get("special_chance", 0.10))))
        max_special_players = max(0, min(player_slots, int(pcfg.get("max_special_players", 2) or 0)))
        tier_weights = {
            "gold": max(0.0, float(pcfg.get("gold_weight", 100) or 0)),
            "silver": max(0.0, float(pcfg.get("silver_weight", 0) or 0)),
            "bronze": max(0.0, float(pcfg.get("bronze_weight", 0) or 0)),
        }
        if sum(tier_weights.values()) <= 0:
            tier_weights = {"gold": 100.0, "silver": 0.0, "bronze": 0.0}

        special_weights = {}
        for k, v in pcfg.get("_special_weights", {}).items():
            try:
                rf = int(k)
                if rf in (12, 15):
                    continue
                special_weights[rf] = max(0.0, float(v))
            except Exception:
                pass

        def weighted_choice(opts):
            arr = [(v, float(w)) for v, w in opts if float(w) > 0]
            if not arr:
                return None
            total = sum(w for _, w in arr)
            r = random.random() * total
            acc = 0.0
            for v, w in arr:
                acc += w
                if r <= acc:
                    return v
            return arr[-1][0]

        def choose_tier():
            return weighted_choice(list(tier_weights.items())) or "gold"

        def tier_for(meta):
            t = str(meta.get("tier", "") or "").lower()
            if t in ("gold", "silver", "bronze"):
                return t
            r = int(meta.get("rating", 0) or 0)
            return "gold" if r >= 75 else "silver" if r >= 65 else "bronze"

        player_pools = {t: {"common": [], "rare": [], "special": []} for t in ("gold", "silver", "bronze")}
        for rid0 in PLAYER_DB.keys():
            rid = int(rid0)
            meta = player_meta(rid)
            t = tier_for(meta)
            rf = int(meta.get("rareflag", 0) or 0)
            issp = bool(meta.get("special", False)) or rf > 1
            player_pools[t]["special" if issp else "rare" if rf == 1 else "common"].append(rid)
        for t in player_pools:
            for k in player_pools[t]:
                random.shuffle(player_pools[t][k])

        used_players: set[int] = set()

        def pop_unique(pool):
            while pool:
                rid = pool.pop()
                if rid not in used_players:
                    used_players.add(rid)
                    return rid
            return None

        def choose_special(tier):
            by_type = {}
            for rid in player_pools[tier]["special"]:
                if rid in used_players:
                    continue
                rf = int(player_meta(rid).get("rareflag", 0) or 0)
                if float(special_weights.get(rf, 0)) <= 0:
                    continue
                by_type.setdefault(rf, []).append(rid)
            if not by_type:
                return None
            rf = weighted_choice([(rf, float(special_weights.get(rf, 0))) for rf in by_type])
            if rf is None or not by_type.get(int(rf)):
                return None
            rid = random.choice(by_type[int(rf)])
            used_players.add(rid)
            try:
                player_pools[tier]["special"].remove(rid)
            except ValueError:
                pass
            return rid

        player_selected: list[int] = []
        special_players_selected = 0
        for _ in range(player_rare_slots):
            tier = choose_tier()
            allow_special = special_players_selected < max_special_players
            rid = choose_special(tier) if allow_special and random.random() < special_chance else None
            if rid is None:
                rid = pop_unique(player_pools[tier]["rare"])
            # A fallback special is only necessary if the normal rare pool is
            # exhausted; still honour the pack cap whenever possible.
            if rid is None and allow_special:
                rid = choose_special(tier)
            if rid is None:
                for alt in [t for t, w in tier_weights.items() if w > 0 and t != tier]:
                    rid = pop_unique(player_pools[alt]["rare"])
                    if rid is None and allow_special:
                        rid = choose_special(alt)
                    if rid is not None:
                        break
            if rid is None:
                raise RuntimeError("Configured rare/special player pool is empty")
            if int(player_meta(rid).get("rareflag", 0) or 0) > 1:
                special_players_selected += 1
            player_selected.append(rid)

        for _ in range(player_slots - player_rare_slots):
            tier = choose_tier()
            rid = pop_unique(player_pools[tier]["common"])
            if rid is None:
                for alt in [t for t, w in tier_weights.items() if w > 0 and t != tier]:
                    rid = pop_unique(player_pools[alt]["common"])
                    if rid is not None: break
            if rid is None:
                raise RuntimeError("Configured common player pool is empty")
            player_selected.append(rid)

        # Build consumable pools by pack tier. These are instance cards (not fake players),
        # so they do not interfere with duplicate-player ownership checks.
        misc_pools = {t: {"common": [], "rare": []} for t in ("gold", "silver", "bronze")}
        misc_family = str(pcfg.get("misc_family", "") or "").lower()
        for spec in CONSUMABLE_CATALOG:
            if misc_family and _consumable_family_from_definition(spec) != misc_family:
                continue
            tier = str(spec.get("tier", "gold") or "gold")
            if tier not in misc_pools:
                continue
            misc_pools[tier]["rare" if int(spec.get("rareflag", 0) or 0) else "common"].append(spec)
        for t in misc_pools:
            for k in misc_pools[t]:
                random.shuffle(misc_pools[t][k])

        used_misc: set[int] = set()
        def pop_misc(tier: str, rarity: str):
            pool = misc_pools[tier][rarity]
            while pool:
                spec = pool.pop()
                rid = int(spec.get("resourceId", 0) or 0)
                if rid and rid not in used_misc:
                    used_misc.add(rid)
                    return spec
            return None

        misc_selected: list[dict[str, Any]] = []
        for _ in range(misc_rare_slots):
            tier = choose_tier()
            spec = pop_misc(tier, "rare")
            if spec is None:
                for alt in [t for t, w in tier_weights.items() if w > 0 and t != tier]:
                    spec = pop_misc(alt, "rare")
                    if spec is not None: break
            if spec is None:
                # Retail packs can contain multiple copies of the same consumable
                # definition. Our compact local catalogue has fewer distinct rare
                # Gold definitions than a 12-card Rare Consumables Pack, so allow
                # definition repeats after exhausting unique rows.
                candidates = [x for x in CONSUMABLE_CATALOG if str(x.get("tier")) == tier and int(x.get("rareflag", 0) or 0) > 0 and (not misc_family or _consumable_family_from_definition(x) == misc_family)]
                spec = random.choice(candidates) if candidates else None
            if spec is None:
                raise RuntimeError("Configured rare consumable pool is empty")
            misc_selected.append(spec)
        for _ in range(misc_slots - misc_rare_slots):
            tier = choose_tier()
            spec = pop_misc(tier, "common")
            if spec is None:
                # Real packs can contain repeated consumable definitions. If our deliberately
                # small catalogue runs out, choose again rather than silently filling with players.
                candidates = [x for x in CONSUMABLE_CATALOG if str(x.get("tier")) == tier and int(x.get("rareflag", 0) or 0) == 0 and (not misc_family or _consumable_family_from_definition(x) == misc_family)]
                spec = random.choice(candidates) if candidates else None
            if spec is None:
                raise RuntimeError("Configured common consumable pool is empty")
            misc_selected.append(spec)

        club_pool = [dict(x) for x in CLUB_COSMETIC_CATALOG if str(x.get("itemType", "")) in {"kit","stadium","custom","ball"}]
        random.shuffle(club_pool)
        club_selected: list[dict[str, Any]] = []
        if club_item_slots:
            rares = [x for x in club_pool if int(x.get("rareflag", 0) or 0) > 0]
            commons = [x for x in club_pool if int(x.get("rareflag", 0) or 0) == 0]
            for _ in range(club_rare_slots):
                club_selected.append((rares or club_pool).pop() if (rares or club_pool) else {})
            for _ in range(club_item_slots - club_rare_slots):
                src = commons or rares or club_pool
                if src: club_selected.append(src.pop())
        descriptors: list[tuple[str, Any]] = [("player", rid) for rid in player_selected] + [("consumable", spec) for spec in misc_selected] + [("clubitem", spec) for spec in club_selected if spec]
        def desc_sort_key(desc):
            kind, value = desc
            if kind == "player":
                meta = player_meta(int(value))
                rf = int(meta.get("rareflag", 0) or 0)
                rating = int(meta.get("rating", 0) or 0)
                special = bool(meta.get("special", False)) or rf > 1
                rid = int(value)
                return (0 if special else 1, -rf, -rating, 0, -rid)
            spec = value
            rf = int(spec.get("rareflag", 0) or 0)
            rating = int(spec.get("rating", 0) or 0)
            rid = int(spec.get("resourceId", 0) or 0)
            return (2, -rf, -rating, 1, -rid)
        descriptors = sorted(descriptors, key=desc_sort_key)

        owned_before = self.owned_player_resource_ids()
        created_reversed = []
        for kind, value in reversed(descriptors):
            if kind == "player":
                created_reversed.append(self.make_player_item(int(value), "unassigned"))
            elif kind == "clubitem":
                spec = dict(value); spec["itemState"] = "free"
                created_reversed.append(self.make_club_item(spec, "unassigned"))
            else:
                created_reversed.append(self.make_consumable_item(value, "unassigned"))
        items = list(reversed(created_reversed))
        base_ts = now_s()
        for rank, item in enumerate(items):
            item["timestamp"] = base_ts - rank
            with self.lock:
                self.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(item), int(item.get("id", 0))))
        with self.lock:
            self.conn.commit()

        dup_ids = [int(x["id"]) for x in items if str(x.get("itemType", "player")) == "player" and int(x.get("resourceId", x.get("assetId", 0)) or 0) in owned_before]
        dup_list = []
        for x in items:
            iid = int(x.get("id", 0) or 0)
            if iid not in dup_ids:
                continue
            rid = int(x.get("resourceId", x.get("assetId", 0)) or 0)
            own = self.owned_player_item_by_resource_id(rid)
            ownid = int(own.get("id", 0) or 0) if isinstance(own, dict) else 0
            dup_list.append({"itemId": iid, "duplicateItemId": ownid} if ownid else {"itemId": iid})
        for iid in dup_ids:
            self.mark_item_duplicate(iid, True)
        if dup_ids:
            refreshed = {int(x.get("id", 0)): x for x in self.list_items("unassigned")}
            items = [refreshed.get(int(x.get("id", 0)), x) for x in items]

        items = sorted(items, key=lambda x: (
            0 if (str(x.get("itemType", "player")) == "player" and (bool(x.get("special", False)) or int(x.get("rareflag", 0) or 0) > 1)) else 1 if str(x.get("itemType", "player")) == "player" else 2,
            -int(x.get("rareflag", 0) or 0), -int(x.get("rating", 0) or 0), -int(x.get("resourceId", x.get("assetId", 0)) or 0)
        ))
        player_count = sum(1 for x in items if str(x.get("itemType", "player")) == "player")
        consumable_count = sum(1 for x in items if int(x.get("resourceId", 0) or 0) in CONSUMABLE_BY_RESOURCE)
        club_count = len(items) - player_count - consumable_count
        log.warning("RETAIL PACK id=%s name=%s size=%d players=%d consumables=%d clubItems=%d rareSlots=%d specialChance=%.1f%% maxSpecials=%d actualSpecials=%d",
                    pack_id, pcfg.get("name"), pack_size, player_count, consumable_count, club_count, rare_slots,
                    special_chance * 100, max_special_players,
                    sum(1 for rid0 in player_selected if int(player_meta(rid0).get("rareflag", 0) or 0) > 1))
        if items:
            log.warning("PACK HEADLINE CANDIDATE id=%s resource=%s type=%s rating=%s rareflag=%s discardValue=%s",
                        items[0].get("id"), items[0].get("resourceId"), items[0].get("itemType"), items[0].get("rating"),
                        items[0].get("rareflag"), items[0].get("discardValue"))
        return {"packId": int(pack_id), "purchasedPackId": int(pack_id), "packType": "CUSTOM_PACK",
                "itemList": items, "itemData": items, "items": items,
                "newcards": len(items) - len(dup_ids), "numberItems": len(items),
                "duplicateItemIdList": dup_list, "credits": self.credits()}


def _native_pack_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return the item shape used by native FUT pack/unassigned responses.

    Keep the real resourceId (the client uses it to resolve the player/card), but
    omit local-only/derived keys that are not part of the original pack item
    payload.  In particular, do not send assetId alongside resourceId here: the
    native client derives the base asset from resourceId.
    """
    out = dict(item)
    # Keep assetId on FIFA 15 PC. Removing it can make some base cards render
    # as NOT FOUND even when resourceId is valid. Only strip server-only fields.
    for key in ("pile", "special", "tier", "wefutCard"):
        out.pop(key, None)
    return out


def _migrate_legacy_localappdata_database() -> None:
    """Copy the pre-v0.2.29 save into the canonical LocalAppData root once."""
    if DB_PATH.exists() or not LEGACY_DB_PATH.exists():
        return
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(LEGACY_DB_PATH)
        dst = sqlite3.connect(DB_PATH)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        log.warning("SAVE MIGRATION copied %s -> %s", LEGACY_DB_PATH, DB_PATH)
    except Exception as exc:
        log.warning("SAVE MIGRATION failed %s -> %s: %s", LEGACY_DB_PATH, DB_PATH, exc)
        # Never continue on a partially-created replacement database; that could
        # look like a fresh club and hide the real migration failure.
        try:
            DB_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        raise


_migrate_legacy_localappdata_database()
STATE = State(DB_PATH)


def _sanitize_offline_season_state_startup() -> None:
    """Prevent FIFA from receiving an impossible half-active fresh season.

    A prior run can persist offline_season_active=True without FIFA ever
    authoring either opaque SeasonData or progressData. That state is exactly
    what the Seasons client rejects while opening the mode. Clear only the
    current-season active flag in that case; preserve club, items, coins and
    all-time record.
    """
    try:
        active = bool(STATE.get("offline_season_active", False))
        data = str(STATE.get("offline_season_wire_data", "") or "")
        progress = str(STATE.get("offline_season_wire_progress_data", "") or "")
        if active and not data and not progress:
            STATE.set("offline_season_active", False)
            log.warning("SEASONS STARTUP SANITIZER cleared stale active=True with no SeasonData/progressData")
    except Exception:
        log.exception("SEASONS STARTUP SANITIZER failed")


_sanitize_offline_season_state_startup()


def _repair_zero_game_active_season_once() -> None:
    """One-time repair for legacy current-season state that advertises active=True
    while still being a zero-game Division 10 bootstrap. Preserve the FUT club,
    coins, items, squad and all-time record; clear only the current season wire state.
    """
    try:
        if bool(STATE.get("season_zero_game_repair_done", False)):
            return
        active = bool(STATE.get("offline_season_active", False))
        st = STATE.offline_season_state()
        zero_game = (
            int(st.get("round", 0) or 0) <= 1
            and int(st.get("points", 0) or 0) == 0
            and int(st.get("wins", 0) or 0) == 0
            and int(st.get("draws", 0) or 0) == 0
            and int(st.get("losses", 0) or 0) == 0
            and int(st.get("goals_for", 0) or 0) == 0
            and int(st.get("goals_against", 0) or 0) == 0
        )
        if active and zero_game:
            for key in (
                "offline_season_points", "offline_season_round",
                "offline_season_wins", "offline_season_draws", "offline_season_losses",
                "offline_season_goals_for", "offline_season_goals_against",
            ):
                STATE.set(key, 0)
            STATE.set("offline_season_active", False)
            STATE.set("offline_season_wire_round", 1)
            STATE.set("offline_season_wire_data", "")
            STATE.set("offline_season_wire_data_version", 1)
            STATE.set("offline_season_wire_progress_data", "")
            STATE.set("offline_season_wire_progress_version", 1)
            STATE.set("awaiting_post_match_season_save", False)
            STATE.set("offline_match_pending", False)
            STATE.set("last_match_end_response", {})
            log.warning("SEASONS v0.2.43 one-time repair: cleared zero-game active current-season wire state; club/items/coins/all-time record preserved")
        STATE.set("season_zero_game_repair_done", True)
    except Exception:
        log.exception("SEASONS v0.2.43 zero-game repair failed")


_repair_zero_game_active_season_once()


def _club_name() -> str:
    return str(STATE.get("club_name", CFG.get("club_name", "Local FC")) or "Local FC")


def _club_abbr() -> str:
    return str(STATE.get("club_abbr", CFG.get("club_abbr", "LCL")) or "LCL")


def _persona_name() -> str:
    return str(STATE.get("persona_name", CFG.get("display_name", "LocalPlayer")) or "LocalPlayer")


def local_user_info() -> dict[str, Any]:
    return {
        "personaId": int(CFG["persona_id"]),
        "personaName": _persona_name(),
        "nucleusId": int(CFG["nucleus_id"]),
        "clubId": int(CFG["club_id"]),
        "clubName": _club_name(),
        "clubAbbr": _club_abbr(),
        "credits": STATE.credits(),
    }


def account_info() -> dict[str, Any]:
    club = {
        "clubId": int(CFG["club_id"]),
        "clubName": _club_name(),
        "clubAbbr": _club_abbr(),
        "year": 2015,
        "lastAccessTime": now_s(),
        "skuAccessList": [CFG["game_sku"]],
    }
    persona = {
        "personaId": int(CFG["persona_id"]),
        "personaName": _persona_name(),
        "userClubList": [club],
    }
    return {
        "userAccountInfo": {
            "nucleusId": int(CFG["nucleus_id"]),
            "personas": [persona],
        },
        "personas": [persona],
    }


def user_mass_info() -> dict[str, Any]:
    return {
        "userInfo": {
            "personaId": int(CFG["persona_id"]),
            "clubId": int(CFG["club_id"]),
            "credits": STATE.credits(),
            "established": 2014,
            "feature": {
                "trade": 1,
                "store": 1,
                "squad": 1,
                "friends": 0,
            },
            "pileSizeClientData": {
                "entries": [
                    {"key": "tradePile", "value": 100},
                    {"key": "watchList", "value": 50},
                    {"key": "duplicateStorage", "value": 100},
                ]
            },
        },
        "credits": STATE.credits(),
    }


def club_info() -> dict[str, Any]:
    items = STATE.list_items("club")
    return {
        "clubInfo": {
            "clubId": int(CFG["club_id"]),
            "clubName": _club_name(),
            "clubAbbr": _club_abbr(),
            "established": 2014,
            "credits": STATE.credits(),
        },
        "clubId": int(CFG["club_id"]),
        "clubName": _club_name(),
        "clubAbbr": _club_abbr(),
        "clubCount": len(items),
        "itemData": items,
        "credits": STATE.credits(),
    }


def store_info() -> dict[str, Any]:
    pack = {
        "id": 1,
        "packId": 1,
        "packType": "LOCAL_GOLD",
        "packTypeId": 1,
        "name": "Local Gold Pack",
        "description": "12 local FUT items",
        "coins": int(CFG.get("pack_cost", 7500)),
        "points": 0,
        "numberItems": int(CFG.get("pack_size", 12)),
        "numItems": int(CFG.get("pack_size", 12)),
        "rare": 3,
        "isAvailableInStore": True,
        "isavailableinstore": True,
        "categoryId": 1,
        "packContentInfo": {
            "gold": int(CFG.get("pack_size", 12)),
            "rare": 3,
            "items": int(CFG.get("pack_size", 12)),
        },
    }
    return {
        "storeEnabled": True,
        "cardPackStoreEnabled": True,
        "packList": [pack],
        "packTypes": [pack],
        "credits": STATE.credits(),
    }


def purchased_info() -> dict[str, Any]:
    return {
        "unopenedPacks": 0,
        "packList": [],
        "purchasedItems": [],
        "credits": STATE.credits(),
    }


def _pow_sid() -> str:
    return "pow." + hashlib.sha256(("POW-" + STATE.token()).encode("utf-8")).hexdigest()[:32]


def _ut_sid() -> str:
    return "ut." + hashlib.sha256(("UT-" + STATE.sid()).encode("utf-8")).hexdigest()[:32]


def _credits_payload() -> dict[str, Any]:
    credits = STATE.credits()
    # FIFA 15 has more than one balance parser. The /user/credits refresh path
    # reads the flat balance members as well as currencies[]. Omitting them can
    # reset the visible FUT header to zero even while SQLite still has the coins.
    return {
        "coins": credits,
        "credits": credits,
        "totalCredits": credits,
        "funds": credits,
        "finalFunds": credits,
        "currencies": [
            {"name": "coins", "funds": credits, "finalFunds": credits},
            {"name": "points", "funds": 0, "finalFunds": 0},
        ],
        "unopenedPacks": {"preOrderPacks": 0, "recoveredPacks": 0},
    }


def _active_club_items() -> list[dict[str, Any]]:
    states = {"activeStadium", "activeHomeKit", "activeAwayKit", "activeBadge", "activeBall"}
    rows = [x for x in STATE.list_items("club") if str(x.get("itemState", "")) in states]
    order = {"activeStadium":0,"activeHomeKit":1,"activeAwayKit":2,"activeBadge":3,"activeBall":4}
    return sorted(rows, key=lambda x: order.get(str(x.get("itemState", "")), 99))

def _display_sort_alias(item: dict[str, Any], rank: int) -> dict[str, Any]:
    """Return a response-only FIFA item with a sortable resourceId alias.

    FIFA 15 PC re-sorts the New Items carousel by resourceId ascending. The
    persistent/local item keeps its real resourceId; only the HTTP response gets
    an alias whose high byte encodes the desired reveal rank while the low 24
    bits keep the real base asset/player id. assetId remains the real base id.
    """
    out = dict(item)
    if str(out.get("itemType", "player")) != "player":
        return out
    try:
        asset = int(out.get("assetId", 0) or 0) & 0x00FFFFFF
    except Exception:
        asset = 0
    # rank 0 -> 0x01000000 + asset, rank 1 -> 0x02000000 + asset, etc.
    # This preserves the base-player portion while forcing ascending client sort.
    out["resourceId"] = (((int(rank) + 1) & 0x7F) << 24) | asset
    return out


def _native_consumable_item(item: dict[str, Any], *, pile: int = 7) -> dict[str, Any]:
    """Return the narrow retail consumable ItemData shape used by CardsDLL.

    Local persistence uses friendly string piles/categories, but the PC apply-
    consumable cache expects a retail numeric club pile and the original
    cardassetid/cardsubtypeid definition fields. Do not leak local-only schema
    members such as category/kind/quality into this cache response.
    """
    try:
        rid = int(item.get("resourceId", 0) or 0)
    except Exception:
        rid = 0
    definition = CONSUMABLE_BY_RESOURCE.get(rid, {})
    source = dict(definition)
    source.update(item)
    rare = int(source.get("rareFlag", source.get("rareflag", 0)) or 0)
    out = {
        "id": int(source.get("id", source.get("itemId", 0)) or 0),
        "itemId": int(source.get("id", source.get("itemId", 0)) or 0),
        "timestamp": int(source.get("timestamp", now_s()) or now_s()),
        "resourceId": rid,
        "cardassetid": int(source.get("cardassetid", 0) or 0),
        "cardsubtypeid": int(source.get("cardsubtypeid", 0) or 0),
        "rating": int(source.get("rating", 0) or 0),
        "rareFlag": rare,
        "rareflag": rare,
        "bronze": int(source.get("bronze", 0) or 0),
        "silver": int(source.get("silver", 0) or 0),
        "gold": int(source.get("gold", 0) or 0),
        "amount": int(source.get("amount", 0) or 0),
        "itemType": str(source.get("itemType", "development") or "development"),
        "resourceGameYear": 2015,
        "discardValue": max(0, int(source.get("discardValue", 0) or 0)),
        "lastSalePrice": max(0, int(source.get("lastSalePrice", 0) or 0)),
        "owners": max(1, int(source.get("owners", 1) or 1)),
        "untradeable": bool(source.get("untradeable", False)),
        "tradeable": not bool(source.get("untradeable", False)),
        "itemState": "free",
        "pile": int(pile),
    }
    # Generate the named applicability members from the canonical category.
    # Do not copy legacy source counters: some old catalogue sourceMember labels
    # were inconsistent (for example an outfield Training row labelled as GK).
    family = _consumable_family_from_definition(definition)
    category = str(definition.get("category", "") or "").casefold()
    amount = int(definition.get("amount", source.get("amount", 0)) or 0)
    if family == "contracts":
        out["consumablesContractPlayer"] = max(1, int(out.get("consumablesContractPlayer", 0) or 0))
    elif family == "managercontracts":
        out["consumablesContractManager"] = max(1, int(out.get("consumablesContractManager", 0) or 0))
    elif family == "fitness":
        if str(definition.get("kind", "") or "").casefold() == "squad":
            out["consumablesFitnessTeam"] = max(1, amount)
        else:
            out["consumablesFitnessPlayer"] = max(1, amount)
    elif family == "healing":
        out["consumablesHealing"] = max(1, amount)
    elif family == "training":
        out["consumablesTraining"] = 1
        if category == "gk training":
            out["consumablesTrainingGk"] = max(1, amount)
        else:
            out["consumablesTrainingPlayer"] = max(1, amount)
    elif family == "position":
        out["consumablesPosition"] = 1
    elif family == "playstyle":
        out["consumablesTrainingPlayerPlayStyle"] = 1
    elif family == "managerleague":
        out["consumablesTrainingManagerLeagueModifier"] = 1
    return out


def _native_player_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a stored player without dropping retail identity/state fields.

    Pack/unassigned responses carry these members directly from the persisted
    item.  The old club/squad/transfer serializer accidentally stripped several
    of them (most importantly resourceGameYear), so the native client could
    render the card but classify it as an ineligible/non-tradeable entity when
    building its action menu.  Keep the compact normalized shape, but preserve
    the fields FIFA 15 uses to identify and act on the owned item.
    """
    resource_id = int(item.get("resourceId", item.get("assetId", 0)) or 0)
    asset_id = int(item.get("assetId", resource_id) or 0)
    team_id = int(item.get("teamid", item.get("teamId", 0)) or 0)
    untradeable = bool(item.get("untradeable", False))
    out = {
        "id": int(item.get("id", item.get("itemId", 0)) or 0),
        "itemId": int(item.get("id", item.get("itemId", 0)) or 0),
        "assetId": asset_id,
        "definitionId": asset_id,
        "resourceId": resource_id,
        "resourceGameYear": int(item.get("resourceGameYear", 2015) or 2015),
        "attributeList": item.get("attributeList", []) if isinstance(item.get("attributeList", []), list) else [],
        "cardsubtypeid": int(item.get("cardsubtypeid", 1) or 0),
        "contract": int(item.get("contract", item.get("contracts", 7)) or 0),
        "contracts": int(item.get("contracts", item.get("contract", 7)) or 0),
        "discardValue": int(item.get("discardValue", 600) or 0),
        "fitness": int(item.get("fitness", 99) or 0),
        "formation": str(item.get("formation", "f442") or "f442"),
        "injuryGames": int(item.get("injuryGames", 0) or 0),
        "injuryType": item.get("injuryType", "none") if item.get("injuryType", "none") is not None else "none",
        "itemState": str(item.get("itemState", "free") or "free"),
        "itemType": "player",
        "lastSalePrice": int(item.get("lastSalePrice", 0) or 0),
        "leagueId": int(item.get("leagueId", 0) or 0),
        "loans": int(item.get("loans", 0) or 0),
        "loyaltyBonus": int(item.get("loyaltyBonus", 1) or 0),
        "marketDataMinPrice": int(item.get("marketDataMinPrice", 150) or 0),
        "marketDataMaxPrice": int(item.get("marketDataMaxPrice", 15000000) or 0),
        "morale": int(item.get("morale", 50) or 0),
        "nation": int(item.get("nation", 0) or 0),
        "owners": max(1, int(item.get("owners", 1) or 1)),
        "preferredPosition": str(item.get("preferredPosition", "") or ""),
        "rareflag": int(item.get("rareflag", CFG.get("rare_flag", 1)) or 0),
        "rating": int(item.get("rating", 0) or 0),
        "suspension": int(item.get("suspension", 0) or 0),
        "teamid": team_id,
        "teamId": team_id,
        "timestamp": int(item.get("timestamp", STATE.get("established", now_s())) or 0),
        "training": int(item.get("training", 0) or 0),
        "trainingId": int(item.get("training", 0) or 0),
        "trainingResourceId": int(item.get("trainingResourceId", 0) or 0),
        "untradeable": untradeable,
        "tradeable": bool(item.get("tradeable", not untradeable)),
        "playStyle": int(item.get("playStyle", 0) or 0),
        "posMods": item.get("posMods", []) if isinstance(item.get("posMods", []), list) else [],
        "statsList": item.get("statsList", []) if isinstance(item.get("statsList", []), list) else [],
        "lifetimeStats": item.get("lifetimeStats", []) if isinstance(item.get("lifetimeStats", []), list) else [],
        "assists": int(item.get("assists", 0) or 0),
        "lifetimeAssists": int(item.get("lifetimeAssists", 0) or 0),
    }
    return out


def _native_squad(requested_id: int | None = None) -> dict[str, Any]:
    squads = STATE.list_squads()
    src: dict[str, Any] | None = None
    if requested_id not in (None, 0):
        src = next((dict(x) for x in squads if int(x.get("id", x.get("squadId", 0)) or 0) == int(requested_id)), None)
    if src is None:
        src = next((dict(x) for x in squads if bool(x.get("active", False))), dict(squads[0]) if squads else None)
    if src is None:
        src = {"id": 1, "squadName": "Local XI", "formation": "f442", "players": []}
    item_by_id = {int(x.get("id", 0)): x for x in STATE.list_items()}

    positions: dict[int, dict[str, Any]] = {}
    for pos in src.get("players", []) if isinstance(src.get("players"), list) else []:
        if not isinstance(pos, dict):
            continue
        iid = pos.get("itemId")
        if iid is None and isinstance(pos.get("itemData"), dict):
            iid = pos["itemData"].get("id")
        try:
            iid_int = int(iid)
            idx = int(pos.get("index", len(positions)))
        except Exception:
            continue
        item = item_by_id.get(iid_int)
        if item:
            positions[idx] = {
                "index": idx,
                "kitNumber": int(pos.get("kitNumber", idx + 1) or 0),
                "itemData": _native_player_item(item),
            }

    # The native response contains all 23 squad slots, including empty ones.
    players: list[dict[str, Any]] = []
    for idx in range(23):
        players.append(positions.get(idx, {"index": idx, "kitNumber": 0}))

    populated = [x for x in players if isinstance(x.get("itemData"), dict)]
    sid = int(src.get("id") or src.get("squadId") or 1)
    name = str(src.get("squadName") or src.get("name") or "Local XI")
    captain = int(src.get("captain") or (populated[0]["itemData"]["id"] if populated else 0))
    kick_ids = [int(x["itemData"]["id"]) for x in populated[:5]]
    while kick_ids and len(kick_ids) < 5:
        kick_ids.append(kick_ids[-1])
    kicktakers = [{"index": i, "id": iid, "dream": False} for i, iid in enumerate(kick_ids)]

    actives = _active_club_items()
    return {
        "id": sid,
        "personaId": int(CFG["persona_id"]),
        "squadName": name,
        "formation": str(src.get("formation") or "f442"),
        "captain": captain,
        "chemistry": int(src.get("chemistry", 100) if src.get("chemistry") is not None else 100),
        "changed": 0,
        "starRating": int(src.get("starRating", 5) or 5),
        "custom": str(src.get("custom") or "[0,0,0,0,0,0,0,0,0,0,0]"),
        "players": players,
        "actives": actives,
        "manager": src.get("manager", []) if isinstance(src.get("manager", []), list) else [],
        "club": actives,
        "kicktakers": kicktakers,
    }


def _compact_squad_record(src: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(src.get("id", src.get("squadId", 0)) or 0),
        "personaId": int(CFG.get("persona_id", 1)),
        "squadName": str(src.get("squadName") or src.get("name") or "Local XI"),
        "formation": str(src.get("formation") or "f442"),
        "active": bool(src.get("active", False)),
        "changed": bool(src.get("changed", False)),
        "chemistry": int(src.get("chemistry", 0) or 0),
        "starRating": int(src.get("starRating", src.get("rating", 0)) or 0),
        "rating": int(src.get("rating", src.get("starRating", 0)) or 0),
        "valid": bool(src.get("valid", True)),
        "newsquad": int(src.get("newsquad", 0) or 0),
    }

def _native_squad_list() -> dict[str, Any]:
    squads = STATE.list_squads()
    compact = [_compact_squad_record(x) for x in squads]
    active = next((x for x in compact if x.get("active")), compact[0] if compact else None)
    return {
        "activeSquadId": int(active.get("id", 0) if active else 0),
        "squad": compact,
    }


def _native_user() -> dict[str, Any]:
    # Match the *types* and nesting of the successful FIFA 15 response.  The
    # client stops issuing requests if fields such as bidTokens/reliability/
    # squadList have the wrong JSON type, even when the HTTP status is 200.
    club_player_items = [x for x in STATE.list_items("club") if str(x.get("itemType", "player")) == "player"]
    squad_player_items = [x for x in STATE.list_items("squad") if str(x.get("itemType", "player")) == "player"]
    squad = _native_squad()
    squad_players = len(squad_player_items)
    total_players = len(club_player_items) + squad_players
    loose_players = len(club_player_items)
    club_all = STATE.list_items("club")
    club_consumables = [x for x in club_all if int(x.get("resourceId", 0) or 0) in CONSUMABLE_BY_RESOURCE]
    club_cosmetics = [x for x in club_all if str(x.get("itemType", "")).lower() in {"kit","stadium","ball","custom"}]
    actives = _active_club_items()
    return {
        "pileClubPlayers": loose_players,
        "pileSquadPlayers": squad_players,
        "pileConsumables": len(club_consumables),
        "pileManagers": 0,
        "pileClubItems": len(club_cosmetics),
        "pileClubTotal": total_players + len(club_consumables) + len(club_cosmetics),
        "pilePack": len(STATE.list_items("unassigned")),
        "kitCount": len([x for x in club_cosmetics if str(x.get("itemType", "")) == "kit"]),
        "badgeCount": len([x for x in club_cosmetics if str(x.get("itemType", "")) == "custom"]),
        "stadiumCount": len([x for x in club_cosmetics if str(x.get("itemType", "")) == "stadium"]),
        "ballCount": len([x for x in club_cosmetics if str(x.get("itemType", "")) == "ball"]),
        "clubPlayers": total_players,
        "clubItemCount": len(club_cosmetics) + len(club_consumables),
        "clubCount": total_players + len(club_consumables) + len(club_cosmetics),
        "accountCreatedPlatformName": "pc",
        "personaId": int(CFG["persona_id"]),
        "clubName": str(_club_name()),
        "clubAbbr": str(_club_abbr()),
        "clubNameChangeAllowed": 0 if bool(STATE.get("club_setup_complete", False)) else 1,
        "returningUser": 1 if bool(STATE.get("club_setup_complete", False)) else 0,
        "established": str(int(STATE.get("established", now_s()))),
        **_credits_payload(),
        "bidTokens": {"count": 0, "updateTime": 0},
        "divisionOffline": int(STATE.offline_season_state()["division"]),
        "divisionOnline": 10,
        "won": int(STATE.get("record_wins", 0) or 0),
        "draw": int(STATE.get("record_draws", 0) or 0),
        "loss": int(STATE.get("record_losses", 0) or 0),
        "trophies": 0,
        "purchased": False,
        "fifaPointsFromLastYear": 0,
        "fifaPointsTransferredStatus": 0,
        "reliability": {"reliability": 100, "matchUnfinishedTime": 0},
        "actives": actives,
        "squadList": _native_squad_list(),
    }


def _club_stats() -> dict[str, Any]:
    club_items = STATE.list_items("club")
    squad_items = STATE.list_items("squad")
    players = len([x for x in club_items + squad_items if str(x.get("itemType", "player")) == "player"])
    consumable_items = [x for x in club_items if int(x.get("resourceId", 0) or 0) in CONSUMABLE_BY_RESOURCE]
    cosmetic_items = [x for x in club_items if str(x.get("itemType", "")).lower() in {"kit","stadium","ball","custom"}]
    kit_count = len([x for x in cosmetic_items if str(x.get("itemType", "")) == "kit"])
    badge_count = len([x for x in cosmetic_items if str(x.get("itemType", "")) == "custom"])
    stadium_count = len([x for x in cosmetic_items if str(x.get("itemType", "")) == "stadium"])
    ball_count = len([x for x in cosmetic_items if str(x.get("itemType", "")) == "ball"])
    kinds = [str(x.get("consumableKind", "")) for x in consumable_items]
    consumables_contract = sum(1 for x in kinds if x.startswith("contract_"))
    consumables_fitness = sum(1 for x in kinds if x.startswith("fitness_"))
    consumables_healing = sum(1 for x in kinds if x == "healing")
    consumables_training = sum(1 for x in kinds if x.startswith("training_"))
    base = {
        "playersEmployed": players,
        "rarePlayersEmployed": players,
        "bronzePlayersEmployed": 0,
        "silverPlayersEmployed": 0,
        "goldPlayersEmployed": players,
        "staffEmployed": 0,
        "kitsAvailable": kit_count,
        "badgesAvailable": badge_count,
        "stadiaOwned": stadium_count,
        "ballsEarned": ball_count,
        "trophiesWon": 0,
        "consumables": len(consumable_items),
        "kits": kit_count,
        "badges": badge_count,
        "stadia": stadium_count,
        "balls": ball_count,
        "trophies": 0,
        "consumablesContract": consumables_contract,
        "consumablesFitness": consumables_fitness,
        "consumablesHealing": consumables_healing,
        "consumablesPlaystyle": 0,
        "consumablesTraining": consumables_training,
        "consumablesTrainingPlayerPlayStyle": 0,
        "consumablesTrainingGkPlayStyle": 0,
        "consumablesContractPlayer": sum(1 for x in kinds if x == "contract_player"),
        "consumablesContractManager": sum(1 for x in kinds if x == "contract_manager"),
        "consumablesFitnessPlayer": sum(1 for x in kinds if x == "fitness_player"),
        "consumablesFitnessTeam": sum(1 for x in kinds if x == "fitness_team"),
        "consumablesTrainingManager": 0,
        "consumablesTrainingPlayer": sum(1 for x in kinds if x == "training_player"),
        "consumablesTrainingGk": 0,
        "consumablesTrainingManagerLeagueModifier": 0,
        "consumablesPosition": 0,
        "consumablesFormationManager": 0,
        "staffHeadCoach": 0,
        "staffFitnessCoach": 0,
        "staffGKCoach": 0,
        "staffPhysio": 0,
        "trophiesOffline": 0,
        "trophiesOnline": 0,
        "trophiesFeaturedOffline": 0,
        "trophiesFeaturedOnline": 0,
        "trophiesSeasonOffline": 0,
        "trophiesSeasonOnline": 0,
    }
    stat_names = [
        ("FUT_MYCLUB_PLAYERS_EMPLOYED", players),
        ("FUT_MYCLUB_RARE_PLAYERS_EMPLOYED", players),
        ("FUT_MYCLUB_GOLD_PLAYERS_EMPLOYED", players),
        ("FUT_MYCLUB_SILVER_PLAYERS_EMPLOYED", 0),
        ("FUT_MYCLUB_BRONZE_PLAYERS_EMPLOYED", 0),
        ("FUT_MYCLUB_TROPHIES_WON", 0),
        ("FUT_MYCLUB_KITS_AVAILABLE", kit_count),
        ("FUT_MYCLUB_BADGES_AVAILABLE", badge_count),
        ("FUT_MYCLUB_STADIA_OWNED", stadium_count),
        ("FUT_MYCLUB_BALLS_EARNED", ball_count),
        ("FUT_MYCLUB_STAFF_EMPLOYED", 0),
        ("players", players), ("playersEmployed", players),
        ("rarePlayers", players), ("rarePlayersEmployed", players),
        ("playersBronze", 0), ("playersSilver", 0), ("playersGold", players),
        ("staff", 0), ("staffEmployed", 0),
        ("kits", kit_count), ("kitsAvailable", kit_count),
        ("badges", badge_count), ("badgesAvailable", badge_count),
        ("stadia", stadium_count), ("stadiaOwned", stadium_count),
        ("balls", ball_count), ("ballsEarned", ball_count),
        ("trophies", 0), ("trophiesWon", 0),
        ("consumables", len(consumable_items)), ("clubPlayers", players), ("playerCount", players),
        ("rareQuantity", players), ("staffManager", 0),
        ("kit", kit_count), ("kitsHome", max(1, kit_count//2)), ("kitsAway", max(1, kit_count//2)),
        ("badge", badge_count), ("timesWon", 0), ("allofflinetrophy", 0),
        ("allonlinetrophy", 0), ("stadium", stadium_count), ("ball", ball_count),
    ]
    base["stat"] = [
        {"type": name, "typeValue": value, "contextId": 0, "contextValue": 0}
        for name, value in stat_names
    ]
    return base


def _consumable_stats() -> dict[str, Any]:
    """Retail named consumable counters used by the squad Apply dialog."""
    known = [
        "consumablesContractPlayer", "consumablesContractManager",
        "consumablesFitnessPlayer", "consumablesFitnessTeam",
        "consumablesHealing", "consumablesTrainingPlayer",
        "consumablesTrainingGk", "consumablesTrainingPlayerPlayStyle",
        "consumablesTrainingGkPlayStyle", "consumablesPosition",
        "consumablesTrainingManager", "consumablesTrainingManagerLeagueModifier",
        "consumablesFormationManager",
    ]
    counts = {key: 0 for key in known}
    family_counts = {
        "contracts": 0, "managercontracts": 0, "fitness": 0, "healing": 0,
        "training": 0, "position": 0, "playstyle": 0, "managerleague": 0,
    }
    total = 0
    for item in STATE.list_items("club"):
        if str(item.get("itemType", "player")) == "player":
            continue
        try:
            rid = int(item.get("resourceId", 0) or 0)
        except Exception:
            continue
        definition = CONSUMABLE_BY_RESOURCE.get(rid)
        if not definition:
            continue
        total += 1
        family = _consumable_family_from_definition(definition)
        if family in family_counts:
            family_counts[family] += 1
        category = str(definition.get("category", "") or "").casefold()
        kind = str(definition.get("kind", "") or "").casefold()
        # Count the exact named members that FIFA's PC Apply Consumable binder
        # checks. Category/class is authoritative; legacy sourceMember is not.
        if family == "contracts":
            counts["consumablesContractPlayer"] += 1
        elif family == "managercontracts":
            counts["consumablesContractManager"] += 1
        elif family == "fitness":
            counts["consumablesFitnessTeam" if kind == "squad" else "consumablesFitnessPlayer"] += 1
        elif family == "healing":
            counts["consumablesHealing"] += 1
        elif family == "training":
            counts["consumablesTrainingGk" if category == "gk training" else "consumablesTrainingPlayer"] += 1
        elif family == "position":
            counts["consumablesPosition"] += 1
        elif family == "playstyle":
            counts["consumablesTrainingPlayerPlayStyle"] += 1
        elif family == "managerleague":
            counts["consumablesTrainingManagerLeagueModifier"] += 1
    counts["consumablesTrainingManager"] = max(counts["consumablesTrainingManager"], family_counts["training"])
    counts["consumablesFormationManager"] = max(counts["consumablesFormationManager"], family_counts["position"])
    counts.update({
        "consumablesContract": family_counts["contracts"] + family_counts["managercontracts"],
        "consumablesFitness": family_counts["fitness"],
        "consumablesTraining": family_counts["training"],
        "consumablesPlaystyle": family_counts["playstyle"],
        "consumables": total,
    })
    entries = [{"contextId": 6, "contextValue": 0, "type": key, "typeValue": int(value)}
               for key, value in sorted(counts.items())]
    doc = dict(counts)
    doc["stat"] = entries
    doc["entries"] = entries
    log.warning("CONSUMABLE STATS total=%s playerContract=%s fitness=%s training=%s position=%s playstyle=%s",
                total, counts.get("consumablesContractPlayer", 0),
                counts.get("consumablesFitnessPlayer", 0) + counts.get("consumablesFitnessTeam", 0),
                counts.get("consumablesTrainingPlayer", 0) + counts.get("consumablesTrainingGk", 0),
                counts.get("consumablesPosition", 0), counts.get("consumablesTrainingPlayerPlayStyle", 0))
    return doc


def _store_purchasegroups() -> dict[str, Any]:
    """Return FIFA's native card-pack offer shape, including real promo deals.

    The earlier v0.2.29 response invented a fourth displayGroup value named
    ``promo``.  The retail-style store contract instead keeps each offer in its
    normal bronze/silver/gold display tier and marks promotional offers with
    dealType=promo.  This is the same separation used by the working local FUT
    market/store implementation and lets the client create its Promo Packs tab.
    """
    credits = STATE.credits()
    settings = load_pack_settings()
    packs: list[dict[str, Any]] = []
    now = now_s()

    for priority, (pid_s, cfg0) in enumerate(
        sorted(settings.get("packs", {}).items(), key=lambda kv: int(kv[0])),
        start=1,
    ):
        if not bool(cfg0.get("enabled", True)):
            continue
        pid = int(pid_s)
        cfg = dict(cfg0)
        name = str(cfg.get("name", f"FUT Pack {pid}") or f"FUT Pack {pid}")
        price = max(0, int(cfg.get("price", 0) or 0))
        qty = max(1, min(30, int(cfg.get("size", 12) or 12)))
        rare = max(0, min(qty, int(cfg.get("rare_slots", 0) or 0)))
        gw = max(0.0, float(cfg.get("gold_weight", 0) or 0))
        sw = max(0.0, float(cfg.get("silver_weight", 0) or 0))
        bw = max(0.0, float(cfg.get("bronze_weight", 0) or 0))
        weight_total = gw + sw + bw
        if weight_total <= 0:
            gw, sw, bw, weight_total = 100.0, 0.0, 0.0, 100.0
        gold = int(round(qty * gw / weight_total))
        silver = int(round(qty * sw / weight_total))
        bronze = max(0, qty - gold - silver)
        tier = max((("gold", gw), ("silver", sw), ("bronze", bw)), key=lambda x: x[1])[0]
        category = str(cfg.get("category", tier) or tier).lower()
        is_promo = category == "promo"

        # Normal pack badges advertise their guaranteed quality count. Promo
        # definitions retain their explicit composition instead.
        tier_quantity = cfg.get("tier_quantity")
        if tier_quantity is not None and not is_promo:
            tq = max(0, min(qty, int(tier_quantity)))
            gold = tq if tier == "gold" else 0
            silver = tq if tier == "silver" else 0
            bronze = tq if tier == "bronze" else 0

        tier_asset_id = {"bronze": 1, "silver": 2, "gold": 3}[tier]
        art_asset_id = max(1, int(cfg.get("art_asset_id", tier_asset_id) or tier_asset_id))
        bio = str(cfg.get("bio", "") or "")
        fifa_points = max(0, int(cfg.get("fifa_points", 0) or 0))
        name_token = f"FUT_STORE_PACK_{pid}_NAME"
        description_token = f"FUT_STORE_PACK_{pid}_DESC"

        offer: dict[str, Any] = {
            "actionType": "CREATEPACK",
            "assetId": art_asset_id,
            "bonus": 0,
            "currencies": [
                {"name": "coins", "funds": price, "finalFunds": price},
                {"name": "points", "funds": fifa_points, "finalFunds": fifa_points},
            ],

            # Keep the literal aliases already proven by this FIFA 15 build,
            # while also supplying the localization tokens used by the native
            # purchase-item contract.
            "name": name,
            "packName": name,
            "displayName": name,
            "title": name,
            "description": name,
            "packDescription": bio,
            "longDescription": bio,
            "shortDescription": bio,
            "bio": bio,
            "label": name,
            "displayLabel": name,
            "storePackName": name,
            "nameToken": name_token,
            "descriptionToken": description_token,

            "displayGroup": {"priority": tier_asset_id, "value": tier},
            "displayGroupAssetId": tier_asset_id,
            "displayGroupUseDefaultImage": True,
            "end": min(2_147_483_647, now + (86400 * 3650)),
            "firstPartyStoreId": "0",
            "id": pid,
            "packId": pid,
            # Keep string packType compatibility and add the numeric identity
            # separately; pack purchases from this PC client submit packId.
            "packType": "PROMO" if is_promo else tier.upper(),
            "packTypeId": pid,
            "purchasePackType": "CARDPACK",
            "purchaseCount": 0,
            "purchaseLimit": 999999,
            "quantity": qty,
            "isPremium": bool(
                is_promo
                or "premium" in name.lower()
                or "rare" in name.lower()
                or "mega" in name.lower()
            ),
            "isSeasonTicketDiscount": False,
            "points": fifa_points,
            "priority": priority,
            "saleType": "NONE",
            "sortPriority": priority,
            "start": max(1, now - 86400),
            "state": "active",
            "unopened": False,
            "useDefaultImage": True,
            "visible": True,
            "isPurchaseable": credits >= price,

            # Compatibility aliases used elsewhere in the FIFA 15 frontend.
            "finalPrice": price,
            "originalPrice": price,
            "group": "promo" if is_promo else tier,
            "groupName": "Promo Packs" if is_promo else (tier.title() + " Packs"),
            "isPromo": is_promo,
            "category": "promo" if is_promo else tier,
            "categoryId": 4 if is_promo else {"bronze": 1, "silver": 2, "gold": 3}[tier],
            "packContentInfo": {
                "itemQuantity": qty,
                "goldQuantity": gold,
                "silverQuantity": silver,
                "bronzeQuantity": bronze,
                "rareQuantity": rare,
            },
        }
        # Crucial: promo is a deal flag, not a displayGroup tier.
        if is_promo:
            offer["dealType"] = "promo"
        packs.append(offer)

    promo_visible = any(bool(x.get("isPromo")) for x in packs)
    category_info = [
        {"id": 1, "categoryId": 1, "name": "Bronze Packs", "groupName": "Bronze Packs",
         "value": "bronze", "displayGroup": "bronze", "sortPriority": 1, "visible": True},
        {"id": 2, "categoryId": 2, "name": "Silver Packs", "groupName": "Silver Packs",
         "value": "silver", "displayGroup": "silver", "sortPriority": 2, "visible": True},
        {"id": 3, "categoryId": 3, "name": "Gold Packs", "groupName": "Gold Packs",
         "value": "gold", "displayGroup": "gold", "sortPriority": 3, "visible": True},
        {"id": 4, "categoryId": 4, "name": "Promo Packs", "groupName": "Promo Packs",
         "value": "promo", "displayGroup": "promo", "sortPriority": 4, "visible": promo_visible},
    ]
    return {
        "purchase": packs,
        "categoryInfo": category_info,
        "categories": category_info,
        "timestamp": now,
    }


def _virtual_market_item(resource_id: int, item_id: int = 0) -> dict[str, Any]:
    meta = player_meta(int(resource_id))
    return {
        "id": int(item_id or (500000000000 + int(resource_id))),
        "timestamp": now_s(),
        "resourceId": int(resource_id),
        "assetId": int(meta.get("assetId", resource_id) or resource_id),
        "rating": int(meta.get("rating", 0) or 0),
        "rareflag": int(meta.get("rareflag", 0) or 0),
        "preferredPosition": str(meta.get("preferredPosition", "") or ""),
        "leagueId": int(meta.get("leagueId", 0) or 0),
        "teamid": int(meta.get("teamid", 0) or 0),
        "nation": int(meta.get("nation", 0) or 0),
        "attributeList": player_attribute_list(int(resource_id)),
        "itemType": "player", "cardsubtypeid": 0, "itemState": "free",
        "contract": 7, "contracts": 7, "fitness": 99, "morale": 50,
        "injuryGames": 0, "injuryType": 0, "training": 0, "suspension": 0,
        "owners": 1, "untradeable": False, "lastSalePrice": 0,
        "discardValue": STATE.player_discard_value(int(resource_id)),
        "loyaltyBonus": 0, "playStyle": 0, "statsList": [], "lifetimeStats": [],
        "assists": 0, "lifetimeAssists": 0,
    }


def _market_copies_per_card() -> int:
    # Trade ids reserve one decimal digit for the virtual copy/slot. Keep this
    # capped at ten so every FIFA 15 card definition can have ten concurrent
    # listings without allocating 170k auction rows in SQLite.
    try:
        copies = int(CFG.get("ai_market_copies_per_card", 10) or 10)
    except Exception:
        copies = 10
    return max(1, min(10, copies))


def _market_card_limit() -> int:
    # v0.2.0-v0.2.5 used ai_market_results=1200 as a hard card cap. 0 means
    # full database in v0.2.7+. A positive value remains available for slow PCs.
    try:
        value = int(CFG.get("ai_market_results", 0) or 0)
    except Exception:
        value = 0
    return max(0, value)


def _market_live_count() -> int:
    if not bool(CFG.get("ai_market_enabled", True)):
        return 0
    card_count = len(PLAYER_DB)
    limit = _market_card_limit()
    if limit:
        card_count = min(card_count, limit)
    return card_count * _market_copies_per_card()


_MARKET_PRICE_CACHE: dict[tuple[int, int], tuple[int, int, int]] = {}

# Buy Now is a two-step client flow: POST /trade/<id>/offer followed immediately
# by GET /trade/status?tradeIds=<id>. v0.2.7 regenerated the deterministic AI
# listing during that status poll, so the auction appeared active again even
# though the purchase had completed. Keep the terminal state long enough for
# FIFA to consume it and clear its market transaction state.
_RECENT_AI_TRADE_STATUS: dict[int, dict[str, Any]] = {}
_RECENT_AI_TRADE_STATUS_TTL = 180

def _market_price_for_resource(resource_id: int, slot: int = 0) -> tuple[int, int, int]:
    key = (int(resource_id), int(slot))
    cached = _MARKET_PRICE_CACHE.get(key)
    if cached is not None:
        return cached
    rid = int(resource_id)
    guide = STATE.market_reference_price(rid)
    seed = int(hashlib.sha1(f"{rid}:{slot}:fut15-local".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    factor = 0.88 + rng.random() * 0.24
    buy_now = max(150, int(guide * factor))
    if buy_now < 1000: step = 50
    elif buy_now < 10000: step = 100
    elif buy_now < 50000: step = 250
    elif buy_now < 100000: step = 500
    else: step = 1000
    buy_now = max(150, int(round(buy_now / step) * step))
    starting = max(150, int(round((buy_now * (0.72 + rng.random()*0.10)) / step) * step))
    out = (starting, buy_now, seed)
    _MARKET_PRICE_CACHE[key] = out
    return out


def _market_listing_for_resource(resource_id: int, slot: int = 0) -> dict[str, Any]:
    rid = int(resource_id)
    slot = max(0, min(9, int(slot)))
    starting, buy_now, seed = _market_price_for_resource(rid, slot)
    trade_id = 700000000000 + rid * 10 + slot
    expires = 240 + (seed % 3300)
    item = _virtual_market_item(rid, 500000000000 + rid * 10 + slot)
    return {
        "tradeId": trade_id,
        "itemData": _native_player_item(item),
        "tradeState": "active", "bidState": "none", "watched": False,
        "startingBid": starting, "currentBid": 0, "buyNowPrice": buy_now,
        "offers": 0, "expires": expires, "confidenceValue": 100,
        "sellerName": "Local Market", "sellerEstablished": 2014,
        "sellerId": 9000000000 + (seed % 999999),
    }

def _market_decode_ai_trade(trade_id: int) -> tuple[int, int] | None:
    v = int(trade_id) - 700000000000
    if v < 0: return None
    rid, slot = divmod(v, 10)
    if rid in PLAYER_DB and 0 <= slot <= 9:
        return int(rid), int(slot)
    return None


def _query_int(query: dict[str, list[str]], names: tuple[str, ...], default: int = 0) -> int:
    for name in names:
        if name in query:
            try: return int(query[name][0] or default)
            except Exception: pass
    return int(default)


def _current_pack_display_alias_map() -> dict[int, int]:
    """Map response-only New Items aliases back to exact persistent card RIDs.

    The New Items carousel sorts by resourceId, so _display_sort_alias() gives
    pack cards temporary revision bytes. Those aliases can collide with genuine
    FIFA 15 special definitions (for example rank-0 TOTY Kroos becomes
    0x01000000|182521 == 16959737, which is his real TOTS definition).
    Compare Price sends that temporary defId back to /transfermarket. Rebuild
    the current carousel mapping from the persistent unassigned pile so the AI
    market can search the exact special version that is actually on screen.
    """
    items = [x for x in STATE.list_items("unassigned") if str(x.get("itemType", "player")) == "player"]

    def _sort_key(item: dict[str, Any]):
        try: rating = int(item.get("rating", 0) or 0)
        except Exception: rating = 0
        try: rareflag = int(item.get("rareflag", 0) or 0)
        except Exception: rareflag = 0
        try: rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
        except Exception: rid = 0
        is_special = bool(item.get("special", False)) or rareflag > 1
        return (0 if is_special else 1, -rating, -rareflag, -rid)

    out: dict[int, int] = {}
    for rank, item in enumerate(sorted(items, key=_sort_key)):
        try:
            asset = int(item.get("assetId", 0) or 0) & 0x00FFFFFF
            real_rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
        except Exception:
            continue
        if not asset or not real_rid:
            continue
        alias = (((rank + 1) & 0x7F) << 24) | asset
        out[int(alias)] = int(real_rid)
    return out


def _market_search(query: dict[str, list[str]]) -> tuple[list[dict[str, Any]], int]:
    start = max(0, _query_int(query, ("start", "offset"), 0))
    num = max(1, min(100, _query_int(query, ("num", "count"), 16)))
    requested_def = _query_int(query, ("maskedDefId", "maskeddefid", "definitionId", "definitionid", "defId", "defid"), 0)
    alias_map = _current_pack_display_alias_map() if requested_def else {}
    masked = int(alias_map.get(int(requested_def), int(requested_def)))
    if requested_def and masked != requested_def:
        log.warning("AI MARKET COMPARE exact-pack-alias requestedDef=%s resolvedRid=%s", requested_def, masked)
    min_buy = max(0, _query_int(query, ("minb", "minBuy", "minbuy"), 0))
    max_buy = max(0, _query_int(query, ("maxb", "maxBuy", "maxbuy"), 0))
    nation = _query_int(query, ("nat", "nation"), 0)
    league = _query_int(query, ("leag", "league"), 0)
    team = _query_int(query, ("team", "club"), 0)
    position = str(query.get("pos", [""])[0] or "").upper()
    zone = str(query.get("zone", [""])[0] or "").lower()
    level = str(query.get("lev", [""])[0] or "").lower()

    def level_ok(meta: dict[str, Any]) -> bool:
        if not level: return True
        tier = str(meta.get("tier", "") or "").lower()
        if not tier:
            r = int(meta.get("rating", 0) or 0); tier = "gold" if r >= 75 else "silver" if r >= 65 else "bronze"
        aliases = {"1":"bronze","2":"silver","3":"gold","bronze":"bronze","silver":"silver","gold":"gold"}
        return tier == aliases.get(level, level)

    def zone_ok(pos: str) -> bool:
        if not zone: return True
        zmap = {
            "attacker": {"ST","CF","LF","RF","LW","RW"}, "attack": {"ST","CF","LF","RF","LW","RW"},
            "midfielder": {"CM","CAM","CDM","LM","RM"}, "midfield": {"CM","CAM","CDM","LM","RM"},
            "defender": {"CB","LB","RB","LWB","RWB"}, "defense": {"CB","LB","RB","LWB","RWB"},
            "goalkeeper": {"GK"}, "gk": {"GK"},
        }
        return pos in zmap.get(zone, {pos})

    candidates: list[int] = []
    for rid0, meta in PLAYER_DB.items():
        rid = int(rid0)
        asset = int(meta.get("assetId", rid) or rid)
        if masked and masked not in (rid, asset): continue
        if nation and int(meta.get("nation", 0) or 0) != nation: continue
        if league and int(meta.get("leagueId", 0) or 0) != league: continue
        if team and int(meta.get("teamid", 0) or 0) != team: continue
        pos = str(meta.get("preferredPosition", "") or "").upper()
        if position and pos != position: continue
        if not zone_ok(pos) or not level_ok(meta): continue
        # Broad guide-price prefilter avoids needless slot checks while still
        # leaving enough margin for each virtual listing's +/-12% variation.
        guide = STATE.market_reference_price(rid)
        if min_buy and guide < int(min_buy * 0.75): continue
        if max_buy and guide > int(max_buy * 1.30): continue
        candidates.append(rid)

    # Stable pseudo-auction order rather than an OVR leaderboard. The expensive
    # listing dictionaries are generated ONLY for the page FIFA requested.
    candidates.sort(key=lambda rid: hashlib.sha1(f"market-order:{rid}".encode()).hexdigest())
    limit = _market_card_limit()
    if limit:
        candidates = candidates[:limit]
    copies = _market_copies_per_card()
    n = len(candidates)
    if not n:
        return [], 0

    # Without price filters the total is exact algebra: all matching card
    # definitions x ten concurrent auctions. Flatten copies by slot so normal
    # pages show lots of different players; a player-specific search shows all
    # ten copies of that card.
    if not min_buy and not max_buy:
        total = n * copies
        page: list[dict[str, Any]] = []
        stop = min(total, start + num)
        for flat in range(start, stop):
            rid = candidates[flat % n]
            slot = flat // n
            page.append(_market_listing_for_resource(rid, slot))
        return page, total

    # Price-filtered searches need the exact per-auction BIN. Walk the lightweight
    # cached price tuples to count matches, but still only materialise the page.
    total = 0
    page: list[dict[str, Any]] = []
    for slot in range(copies):
        for rid in candidates:
            _starting, bin_price, _seed = _market_price_for_resource(rid, slot)
            if min_buy and bin_price < min_buy: continue
            if max_buy and bin_price > max_buy: continue
            if total >= start and len(page) < num:
                page.append(_market_listing_for_resource(rid, slot))
            total += 1
    return page, total

def _transfer_item_payload(item: dict[str, Any], state: str = "free") -> dict[str, Any]:
    """Return ItemData in the native Transfer List pile/state contract."""
    native = _native_player_item(item)
    native["pile"] = 5
    native["itemState"] = state
    native["untradeable"] = False
    native["tradeable"] = True
    return native


def _user_auction_payload(row: dict[str, Any]) -> dict[str, Any]:
    item = STATE.get_item(int(row.get("item_id", 0) or 0))
    if not item:
        raw_snapshot = row.get("item_payload", "{}")
        try:
            item = json.loads(raw_snapshot) if isinstance(raw_snapshot, str) else dict(raw_snapshot or {})
        except Exception:
            item = {}
    if not item:
        item = _virtual_market_item(
            int(row.get("resource_id", 0) or 0),
            int(row.get("item_id", 0) or 0),
        )

    db_state = str(row.get("state", "active") or "active")
    trade_state = "closed" if db_state == "sold" else db_state
    item_state = "sold" if db_state == "sold" else ("forSale" if db_state == "active" else "free")
    remaining = max(0, int(row.get("expires", now_s()) or now_s()) - now_s())
    sold_price = int(row.get("sold_price", 0) or row.get("current_bid", 0) or 0)
    current_bid = sold_price if db_state == "sold" else int(row.get("current_bid", 0) or 0)
    duration = max(60, int(row.get("expires", 0) or 0) - int(row.get("created", 0) or 0))
    display_expires = remaining if db_state == "active" else 0

    payload = {
        "tradeId": int(row.get("trade_id", 0) or 0),
        "tradeState": trade_state,
        "expires": display_expires,
        "EXPIRE_TIME": display_expires,
        "expireTime": display_expires,
        "startTime": 0,
        "endtime": 2147483647,
        "buyNowPrice": int(row.get("buy_now", 0) or 0),
        "startingBid": max(150, int(row.get("starting_bid", 0) or 0)),
        "currentBid": current_bid,
        # A completed local-bot Buy Now is not a pending offer.
        "offers": 0,
        "watched": False,
        "bidState": "none",
        "tradeOwner": True,
        "sellerName": _persona_name(),
        "sellerEstablished": 2014,
        "sellerId": int(CFG.get("persona_id", 1)),
        "confidenceValue": 100,
        "itemData": _transfer_item_payload(item, item_state),
    }
    if db_state == "sold":
        payload["itemData"]["lastSalePrice"] = sold_price
    if int(row.get("market_value_at_list", 0) or 0):
        payload["marketValue"] = int(row.get("market_value_at_list", 0) or 0)
    try:
        meta = json.loads(row.get("data", "{}") or "{}")
        if isinstance(meta, dict) and int(meta.get("cheapestMarketPrice", 0) or 0):
            payload["cheapestMarketPrice"] = int(meta["cheapestMarketPrice"])
    except Exception:
        pass
    return payload


def _unlisted_trade_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Native Transfer List row for a card which has *no auction yet*.

    This deliberately mirrors the retail Auction object's untouched defaults:
    tradeId=0, tradeOwner=false, tradeState=inactive and expires=-1.  v0.2.36/37
    still stamped seller/owner auction metadata onto these rows.  The frontend
    could display the native "not currently listed" prompt, but its action
    controller still saw an owner-auction-shaped object and never fired the
    List-on-Market path when Enter/A was pressed.

    A real owner auction is created only by POST /auctionhouse; that response
    gets a persistent non-zero trade id and tradeOwner=true.
    """
    return {
        "tradeId": 0,
        "tradeIdStr": "0",
        "tradeState": "inactive",
        "expires": -1,
        "buyNowPrice": 0,
        "startingBid": 0,
        "currentBid": 0,
        "offers": 0,
        "watched": False,
        "bidState": "none",
        "tradeOwner": False,
        "itemData": _transfer_item_payload(item, "free"),
    }


def _auction_is_action_bridge(row: dict[str, Any]) -> bool:
    try:
        meta = json.loads(row.get("data", "{}") or "{}")
    except Exception:
        return False
    return isinstance(meta, dict) and bool(meta.get("actionBridge", False))


def _transfer_pile_payload() -> dict[str, Any]:
    """Return the user's persistent Transfer List with selectable auction state."""
    # FIFA 15 PC does not dispatch the List action for a zero-id inactive auction
    # even though it renders the "not currently listed" prompt. Expired owner
    # auctions are selectable, so materialise a lightweight expired trade shell
    # for every pile=trade card which has never had an auction.
    existing = STATE.list_user_auctions()
    auction_item_ids = {int(x.get("item_id", 0) or 0) for x in existing}
    bridged = 0
    for item in STATE.transfer_list_items():
        iid = int(item.get("id", 0) or 0)
        if iid and iid not in auction_item_ids:
            if STATE.ensure_transfer_action_bridge(iid):
                bridged += 1
    auctions = STATE.list_user_auctions()
    info = [_user_auction_payload(x) for x in auctions]
    unlisted = sum(1 for x in auctions if str(x.get("state")) == "expired" and _auction_is_action_bridge(x))
    if bridged:
        log.warning("TRANSFER LIST ACTION BRIDGE materialized=%s", bridged)

    selling = sum(1 for x in auctions if str(x.get("state")) == "active")
    sold = sum(1 for x in auctions if str(x.get("state")) == "sold")
    credits = STATE.credits()
    return {
        "auctionInfo": info,
        "duplicateItemIdList": [],
        "credits": credits,
        "totalCredits": credits,
        "coins": credits,
        "total": len(info),
        "count": len(info),
        "currentTradePileSize": len(info),
        "tradePileCount": len(info),
        "tradePileItems": len(info),
        "transferListCount": len(info),
        "maxAuctionsAllowed": 100,
        "maximumTradePileSize": 100,
        "offered": 0,
        "selling": selling,
        "activeCount": selling,
        "sold": sold,
        "soldCount": sold,
        "available": unlisted,
        "unlisted": unlisted,
        "itemData": [x.get("itemData") for x in info if isinstance(x.get("itemData"), dict)],
    }


def _offline_season_definitions() -> list[dict[str, Any]]:
    """FIFA 15 offline division table using the client-proven FIFA 14 PC ordinal contract.

    The user's working FIFA 14 PC build established a three-way contract that is
    internally consistent in the retail CardsDLL family:
      * /user publishes the human division number (fresh club = 10),
      * season/list exposes all ten records ordered Division 1 -> Division 10,
        with id/divisionId 1..10,
      * season/user stores the inverse internal ordinal (Division 10 -> 1).

    Earlier FIFA 15 probes inverted the list record itself and fabricated a
    different fresh seasonId.  v0.2.16 removes those speculative differences and
    ports the working PC contract while retaining FIFA 15-specific routes/assets.
    """
    # division, matches, promotion threshold, championship coins
    ladder = [
        (1, 10, 23, 10000),
        (2, 10, 21, 7500),
        (3, 10, 19, 6000),
        (4, 10, 18, 5000),
        (5, 10, 16, 4400),
        (6, 10, 16, 3800),
        (7, 10, 14, 3300),
        (8, 10, 13, 2900),
        (9, 10, 11, 2100),
        (10, 10, 9, 1900),
    ]
    defs: list[dict[str, Any]] = []
    for division, matches, promote_pts, championship_coins in ladder:
        difficulty = max(1, min(5, 1 + (10 - division) // 2))
        title_pts = 12 if division == 10 else min(30, promote_pts + 3)
        maintenance_pts = 0 if division == 10 else max(0, promote_pts - 5)
        defs.append({
            "divisionNumber": division,
            "id": division,
            "seasonId": division,
            "divisionId": division,
            "name": f"Division {division}",
            "difficulty": difficulty,
            "numMatches": matches,
            "pointsForTitle": title_pts,
            "pointsForPromotion": promote_pts,
            "pointsForRelegation": maintenance_pts,
            "reward": championship_coins,
        })
    return defs


SEASON_TROPHY_RESOURCE_ID = 1100
SEASON_TROPHY_TIER = "gold"
SEASON_FOREVER = 2147483647  # signed-32-bit max; matches the working PC Seasons contract.
SEASON_ASSET_DIR = Path(__file__).resolve().parent
SEASON_TROPHY_ITEM_BIG = SEASON_ASSET_DIR / "trophy_1100_golditem.big"
SEASON_TROPHY_FULL_BIG = SEASON_ASSET_DIR / "trophy_1100_gold.big"


def _season_trophy_basename(resource_id: int = SEASON_TROPHY_RESOURCE_ID) -> str:
    return f"trophy_{int(resource_id)}_{SEASON_TROPHY_TIER}"


def _empty_big_archive() -> bytes:
    """Last-resort binary response for an unknown trophy BIG request."""
    return b"BIGF" + (16).to_bytes(4, "little") + (0).to_bytes(4, "big") + (16).to_bytes(4, "big")


def _season_trophy_big_response(request_path: str) -> bytes:
    """Serve the real FIFA 15 trophy resource extracted from this build's cards0.big.

    The PC client asks for `/items/images/trophies/kc/item.big`. v0.2.7/v0.2.8
    answered that with a synthetic 16-byte empty archive. FIFA 15's own cards0.big
    contains `trophy_1100_golditem.big`, so use that native payload for the exact
    `item.big` request and the full trophy payload when its explicit name is asked.
    """
    low_path = str(request_path or "").lower()
    candidate = SEASON_TROPHY_ITEM_BIG if low_path.endswith("/item.big") else SEASON_TROPHY_FULL_BIG
    try:
        blob = candidate.read_bytes()
        if blob:
            return blob
    except Exception as exc:
        log.warning("Could not read native season trophy asset %s: %s", candidate, exc)
    return _empty_big_archive()


def _season_trophy_item_response(resource_id: int) -> dict[str, Any]:
    resolved = SEASON_TROPHY_RESOURCE_ID if int(resource_id) <= 0 else int(resource_id)
    basename = _season_trophy_basename(resolved)
    return {
        "itemData": [{
            "id": resolved,
            "assetId": resolved,
            "resourceId": resolved,
            "itemType": "trophy",
            "assetName": basename,
            "name": basename,
            "image": basename,
        }]
    }

def _season_match_records(internal: dict[str, Any]) -> list[dict[str, Any]]:
    """Ten local AI fixtures using member names present in FIFA 15 CardsDLL."""
    division = int(internal["divisionNumber"])
    difficulty = int(internal["difficulty"])
    # Known FIFA 15 club IDs; deliberately varied so the fixture list is not a
    # single repeated opponent. Division 10 starts at low difficulty.
    teams = [1, 5, 7, 9, 10, 11, 21, 22, 73, 243]
    return [
        {
            "teamId": int(teams[i % len(teams)]),
            "difficulty": difficulty,
            "rewardMult": 1,
            "roundId": i,
            "coins": 300 + i * 25 + (10 - division) * 50,
        }
        for i in range(10)
    ]


def _season_prize(level: str, threshold: int, coins: int = 0) -> dict[str, Any]:
    """Native FIFA 15 Season prize record.

    CardsDLL's nested award parser recognizes `type`, `count` and `value`, and
    its enum contains the lower-case `coin` award type. Empty award arrays left
    the Season Rewards column blank in every previous PC probe.
    """
    awards: list[dict[str, Any]] = []
    if int(coins) > 0:
        awards.append({"type": "coin", "value": int(coins), "assetId": 0, "count": 1, "halId": 0, "teamId": 0})
    return {
        "prizeLevel": str(level),
        "thresholdPoint": int(threshold),
        "awardMappings": [{"awards": awards}],
    }


def _season_list_wire_record(internal: dict[str, Any]) -> dict[str, Any]:
    """Exact FIFA 15 PC SeasonList record, limited to members its parser reads."""
    title = int(internal["pointsForTitle"])
    promotion = int(internal["pointsForPromotion"])
    maintenance = int(internal["pointsForRelegation"])
    division = int(internal["divisionNumber"])
    # Small but non-zero Division 10 rewards so the native Season Rewards
    # binding has actual award records to consume.
    championship_coins = int(internal.get("reward", 1900) or 1900)
    promotion_coins = 1500 if division == 10 else max(500, championship_coins - 400)
    maintenance_coins = 300 if division == 10 else max(300, championship_coins // 5)
    return {
        "id": int(internal["id"]),
        # Keep the catalogue identity stable. Reversing these ten values in
        # v0.2.23 made the FIFA 15 PC client crash immediately after parsing
        # SeasonList. The known-working PC contract is id N / divisionId N.
        "divisionId": int(internal["divisionId"]),
        "type": "OFFLINE",
        "numMatches": 10,
        "matchLengthMin": 6,
        "matches": _season_match_records(internal),
        "prizeSet": [
            _season_prize("RELEGATION", 0, 0),
            _season_prize("MAINTENANCE", maintenance, maintenance_coins),
            _season_prize("PROMOTION", promotion, promotion_coins),
            _season_prize("CHAMPIONSHIP", title, championship_coins),
        ],
        "elgOperation": "AND",
        "elgReq": [],
        "trophyResourceId": SEASON_TROPHY_RESOURCE_ID,
        "trophyUseCount": 0,
        "visStartDays": 3650,
        "visEndDays": 3650,
        "startDateTime": 0,
        "endDateTime": SEASON_FOREVER,
        "untilStartSeconds": 0,
        "untilEndSeconds": 315360000,
    }

def _offline_season_user_payload(full: bool = False) -> dict[str, Any]:
    """Return FIFA 15 PC's current offline-season descriptor.

    FIFA 15 uses two division-id contracts. SeasonList is inverted by the
    catalogue parser (Division 10 is wire divisionId=1), while the current/load
    SeasonData parser stores divisionId raw (Division 10 is 10). Keep seasonId
    and URL division numbers human-facing (10) and use raw 10 here.
    """
    st = STATE.offline_season_state()
    division_number = max(1, min(10, int(st.get("division", 10) or 10)))
    all_defs = _offline_season_definitions()
    internal = next((x for x in all_defs if int(x["divisionNumber"]) == division_number), all_defs[-1])
    active = bool(STATE.get("offline_season_active", False))
    # Recover from a stale half-active state left by an interrupted match.
    # FIFA 15 can otherwise receive active=True with no opaque SeasonData or
    # progressData, then terminate while opening Seasons.
    saved_data = str(STATE.get("offline_season_wire_data", "") or "")
    saved_progress = str(STATE.get("offline_season_wire_progress_data", "") or "")
    if active and not saved_data and not saved_progress:
        active = False
        STATE.set("offline_season_active", False)
    # Fresh bootstrap and resumed-season parsing are annoyingly different in
    # FIFA 15 PC. The exact v0.2.13 fresh contract that first opened Seasons
    # used the inverse ordinal (Division 10 -> 1). Once FIFA has authored its
    # own SeasonData and the season is active, v0.2.22 proved raw 10 is required
    # for stable resume. Split those states instead of forcing one value through
    # both parsers.
    saved_data = str(STATE.get("offline_season_wire_data", "") or "")
    active_wire = bool(active or saved_data)
    wire_division = int(division_number if active_wire else (11 - division_number))
    user = {
        "seasonId": int(internal["seasonId"]),
        "divisionId": wire_division,
        "offlineDivision": int(division_number),
        "type": "offline",
        "round": max(1, min(10, int(st.get("round", 0) or 0) + 1)),
        # v0.2.21 accidentally dropped these v0.2.20 underway-state members.
        # Without them GetCurrentSeasonID falls back to StartSeason even when
        # the SQLite state and opaque save are already on Round 2+.
        "active": active,
        "seasonState": "active" if active else "inactive",
        "seasonCompleted": False,
        "seasonEndResult": 0,
        "creationTime": int(STATE.get("established", now_s()) or now_s()),
        "points": int(st.get("points", 0) or 0),
        "wins": int(st.get("wins", 0) or 0),
        "draws": int(st.get("draws", 0) or 0),
        "losses": int(st.get("losses", 0) or 0),
    }
    if int(st.get("round", 0) or 0) > 0:
        saved_progress = str(STATE.get("offline_season_wire_progress_data", "") or "")
        enriched: dict[str, Any] = {}
        if saved_data:
            data_version = max(1, int(STATE.get("offline_season_wire_data_version", 1) or 1))
            # Keep data first: the native SeasonLoadData decoder acts when the
            # version member follows it. The aliases are used by the frontend
            # SeasonAdapter's underway/current-season check.
            enriched["data"] = saved_data
            enriched["dataVersion"] = data_version
            enriched["seasonData"] = saved_data
            enriched["seasonDataVersion"] = data_version
        if saved_progress:
            progress_version = max(1, int(STATE.get("offline_season_wire_progress_version", 1) or 1))
            enriched["progressData"] = saved_progress
            enriched["progressDataVersion"] = progress_version
            enriched["progressdata"] = saved_progress
        enriched.update(user)
        enriched.update({
            "seasonGamesWon": int(st.get("wins", 0) or 0),
            "seasonGamesDraw": int(st.get("draws", 0) or 0),
            "seasonGamesLost": int(st.get("losses", 0) or 0),
        })
        user = enriched
    return user


def _season_progress_wire_payload(season_id: int | None = None, division_number: int | None = None) -> dict[str, Any]:
    """Return the PC SeasonLoadData envelope in the working field order.

    On a fresh season the working PC implementation emits only the proven scalar
    members. Once FIFA authors an opaque Base64 save blob, echo `data` first and
    `dataVersion` second before the scalar state because the native decoder acts
    when it encounters the version field.
    """
    if division_number is None:
        division_number = int(STATE.offline_season_state().get("division", 10) or 10)
    division_number = max(1, min(10, int(division_number)))
    all_defs = _offline_season_definitions()
    internal = next((x for x in all_defs if int(x["divisionNumber"]) == division_number), all_defs[-1])
    sid = int(season_id if season_id is not None else internal["seasonId"])
    document: dict[str, Any] = {}
    saved_data = str(STATE.get("offline_season_wire_data", "") or "")
    if saved_data:
        document["data"] = saved_data
        document["dataVersion"] = max(1, int(STATE.get("offline_season_wire_data_version", 1) or 1))
    saved_progress = str(STATE.get("offline_season_wire_progress_data", "") or "")
    if saved_progress:
        document["progressData"] = saved_progress
        document["progressDataVersion"] = max(1, int(STATE.get("offline_season_wire_progress_version", 1) or 1))
    document["seasonId"] = sid
    # Match the same parser split as season/user: fresh bootstrap uses the
    # proven inverse ordinal; an active/saved season uses the raw division.
    active_wire = bool(STATE.get("offline_season_active", False) or saved_data)
    document["divisionId"] = int(division_number if active_wire else (11 - division_number))
    semantic_round = max(1, min(10, int(STATE.offline_season_state().get("round", 0) or 0) + 1))
    saved_round = max(1, int(STATE.get("offline_season_wire_round", semantic_round) or semantic_round))
    # Never advertise an older opaque-save round than the result already
    # committed by /match/end. This prevents the post-match frontend retry from
    # resurrecting the pre-match round-1 save and visually wiping 3 points.
    document["round"] = max(semantic_round, saved_round)
    return document


def _save_season_progress_wire(payload: dict[str, Any]) -> bool:
    """Persist FIFA's opaque season blob without allowing a stale rollback.

    After a completed match FIFA first writes the correct next-round blob and,
    if GameReporting has not completed, can later retry an old round-1 bootstrap
    save. v0.2.16 accepted that retry and the client then reopened with zero
    visible progress. Semantic W/D/L from /match/end is authoritative.
    """
    if not isinstance(payload, dict):
        return False

    st = STATE.offline_season_state()
    semantic_round = max(1, min(10, int(st.get("round", 0) or 0) + 1))
    current_wire_round = max(1, int(STATE.get("offline_season_wire_round", semantic_round) or semantic_round))
    try:
        incoming_round = max(1, int(payload.get("round", current_wire_round) or current_wire_round))
    except Exception:
        incoming_round = current_wire_round

    has_data = bool(str(payload.get("data", "") or ""))
    awaiting_post = bool(STATE.get("awaiting_post_match_season_save", False))

    # The first client-authored save immediately after a terminal match is the
    # best source of truth for FIFA's opaque fixture/progress table. In
    # particular, forfeits do author a usable post-match blob even though older
    # builds assumed they did not and deleted it. Accept that first blob once,
    # while keeping semantic W/D/L from /match/end authoritative.
    if awaiting_post and has_data:
        # A forfeit used to return endReason=QUIT. FIFA then echoed the *old*
        # pre-match SeasonData (e.g. incoming Round 2 while canonical Round 4),
        # and we incorrectly promoted that stale blob to the current save. Only
        # accept a post-match blob that has actually advanced to the semantic
        # next fixture. v0.2.24 retains LOSS for quit/DNF so the client should
        # author that genuine next-round blob.
        if incoming_round < semantic_round:
            log.warning(
                "SEASONS SAVE rejected stale post-match blob incomingRound=%s canonicalRound=%s; awaiting genuine next-round save",
                incoming_round, semantic_round,
            )
            return False
        STATE.set("offline_season_wire_round", incoming_round)
        STATE.set("awaiting_post_match_season_save", False)
        log.warning(
            "SEASONS SAVE accepted post-match client blob incomingRound=%s canonicalRound=%s state=%s",
            incoming_round, semantic_round, st,
        )
    else:
        # Later retries may genuinely be pre-match/bootstrap state. Reject only
        # those after the one authoritative post-match write has been consumed.
        if int(st.get("round", 0) or 0) > 0 and incoming_round < max(semantic_round, current_wire_round):
            log.warning(
                "SEASONS SAVE ignored stale rollback incomingRound=%s canonicalRound=%s state=%s",
                incoming_round, max(semantic_round, current_wire_round), st,
            )
            return False
        STATE.set("offline_season_wire_round", max(incoming_round, semantic_round))
    for src, dst in (
        ("data", "offline_season_wire_data"),
        ("progressData", "offline_season_wire_progress_data"),
        ("progressdata", "offline_season_wire_progress_data"),
    ):
        if src in payload:
            STATE.set(dst, str(payload.get(src) or ""))
    for src, dst in (
        ("dataVersion", "offline_season_wire_data_version"),
        ("progressDataVersion", "offline_season_wire_progress_version"),
    ):
        if src in payload:
            try:
                STATE.set(dst, int(payload.get(src) or 1))
            except Exception:
                pass
    return True


def _offline_match_reward(doc: dict[str, Any], end_reason: str) -> dict[str, int | float]:
    """Small retail-style FUT match award breakdown.

    This mirrors the proven FIFA 14 PC local implementation closely enough for
    FIFA 15's post-match award screen: completed 90-minute games receive a base
    completion award plus skill bonuses/penalties from the exact stats FIFA
    submitted in DestroyMatch.
    """
    mine = doc.get("myMatchStats") if isinstance(doc.get("myMatchStats"), dict) else {}
    opp = doc.get("opponentMatchStats") if isinstance(doc.get("opponentMatchStats"), dict) else {}
    completed = str(end_reason).upper() in {"WIN", "DRAW", "LOSS"}
    minutes = 90 if completed else 0
    goals = max(0, int(mine.get("goals", 0) or 0))
    against = max(0, int(opp.get("goals", 0) or 0))
    shots = max(0, int(mine.get("shotsOnTarget", 0) or 0))
    tackles = max(0, int(mine.get("successfulTackles", 0) or 0))
    corners = max(0, int(mine.get("corners", 0) or 0))
    pass_accuracy = max(0, min(100, int(mine.get("passingPercentage", 0) or 0)))
    possession = max(0, min(100, int(mine.get("possessionPercentage", 0) or 0)))
    fouls = max(0, int(mine.get("fouls", 0) or 0))
    yellows = max(0, int(mine.get("yellowCards", 0) or 0))
    reds = max(0, int(mine.get("redCards", 0) or 0))
    offsides = max(0, int(mine.get("offsides", 0) or 0))
    motm = 1 if int(mine.get("manOfTheMatch", 0) or 0) else 0
    clean = 1 if completed and against == 0 else 0

    completion = 325 if completed else 0
    skill_raw = (
        min(goals * 40, 200)
        + min(shots * 5, 75)
        + min(tackles, 20)
        + min(corners * 5, 50)
        + (75 if clean else 0)
        + min(pass_accuracy, 80)
        + min(possession, 80)
        + (15 if motm else 0)
        - min(against * 20, 80)
        - min(fouls, 20)
        - min((yellows + reds) * 10, 80)
        - min(offsides, 15)
    )
    skill = max(0, int(round(skill_raw))) if completed else 0
    total = max(0, completion + skill)
    return {
        "minutesPlayed": minutes,
        "secondsPlayed": minutes * 60,
        "completionAward": completion,
        "skillAward": skill,
        "rewardCoins": total,
        "totalCoins": total,
        "dnfModifier": 1.0,
    }



def route_fut(method: str, raw_path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
    # ProtoHttp sends the POW auth path with a double leading slash in the
    # successful FIFA 15 trace. urlsplit("//pow/auth") would otherwise treat
    # "pow" as a network location and lose the /pow prefix.
    if raw_path.startswith("//pow/"):
        raw_path = "/" + raw_path.lstrip("/")
    parsed = urllib.parse.urlsplit(raw_path)
    path = "/" + parsed.path.lstrip("/")
    query = urllib.parse.parse_qs(parsed.query)
    low = path.lower().rstrip("/") or "/"
    payload = safe_json(body)

    # STORE-SCOUT v27: capture the exact endpoints FIFA 15 actually uses for
    # store catalog/title/description data. This is diagnostic only and does
    # not change the working pack/coin/item behavior.
    if any(token in low for token in ("store", "pack", "purchase", "loc")):
        log.warning(
            "STORE-SCOUT REQUEST method=%s path=%s query=%s accept=%s contentType=%s body=%s",
            method,
            raw_path,
            query,
            headers.get("Accept", headers.get("accept", "")),
            headers.get("Content-Type", headers.get("content-type", "")),
            body[:1000],
        )

    # Retail pack backgrounds requested directly by the FUT store.  These
    # PNGs are extracted from this FIFA 15 build's own cards0.big; returning an
    # empty JSON object here (v0.2.26 behavior) leaves the client with mismatched
    # or missing pack art.
    pack_img = re.fullmatch(r"/fut/packs/images/(?:kc|web)/packs_backgrounds_(\d+)\.png", low)
    if pack_img and method == "GET":
        asset_id = int(pack_img.group(1))
        image_path = ROOT / "assets" / "packs" / f"packs_backgrounds_{asset_id}.png"
        if image_path.exists():
            return 200, {"Content-Type":"image/png", "Cache-Control":"public, max-age=3600"}, image_path.read_bytes()
        return 404, {"Content-Type":"text/plain"}, b"pack background not found"

    # ---- POW / EASFC bootstrap --------------------------------------------
    if low == "/pow/auth":
        sid = _pow_sid()
        return 200, {"X-POW-SID": sid}, json_bytes({
            "sid": sid,
            "serverTime": now_s(),
            "lastOnlineTime": now_s(),
        })

    if low.startswith("/pow/"):
        if low == "/pow/bank/user/account":
            return 200, {}, json_bytes({
                "currencies": [{
                    "currency": "pow_funds",
                    "funds": 0,
                    "fundsCapInfo": [
                        {"period": "daily", "fundsEarned": 0},
                        {"period": "weekly", "fundsEarned": 0},
                    ],
                }]
            })
        if low == "/pow/store/game/fifa15/catalog/list":
            return 200, {}, json_bytes({
                "catalogs": [
                    {"catalogId": 0, "name": "FUT Store"},
                    {"catalogId": 1, "name": "FIFAPoints"},
                ]
            })
        if "/catalog/0/item/list" in low:
            return 200, {}, json_bytes({"items": [], "endOfList": True})
        return 200, {}, json_bytes({})

    # ---- FUT authentication -----------------------------------------------
    if low == "/ut/auth":
        if method == "DELETE":
            return 200, {}, json_bytes({})
        sid = _ut_sid()
        return 200, {"X-UT-SID": sid}, json_bytes({"sid": sid, "protocol": "http"})

    if low in ("/ut/shards", "/ut/shards/v2"):
        return 200, {}, json_bytes({
            "shardInfo": [{
                "customdata1": "127.0.0.1",
                "customdata2": str(CFG["fut_port"]),
                "name": "LocalFUT15",
                "platform": "pc",
                "clientFacingIpPort": f"127.0.0.1:{CFG['fut_port']}",
            }]
        })

    if low == "/ut/game/fifa15/user/accountinfo":
        return 200, {}, json_bytes({
            "userAccountInfo": {
                "personas": [{
                    "personaId": int(CFG["persona_id"]),
                    "personaName": str(_persona_name()),
                    "userClubList": [{
                        "year": "2015",
                        "platform": "pc",
                        "clubName": str(_club_name()),
                        "established": int(STATE.get("established", now_s()) or now_s()),
                        "assetId": int(CFG["club_id"]),
                        "clubAbbr": str(_club_abbr()),
                    }],
                    "returningUser": 1,
                }]
            }
        })

    if low == "/ut/game/fifa15/user/club" and method in ("PUT", "POST"):
        src = payload if isinstance(payload, dict) else {}
        profile = STATE.update_profile(src)
        return 200, {"Cache-Control": "no-store"}, json_bytes({
            "clubId": int(CFG["club_id"]),
            "clubName": profile["clubName"],
            "clubAbbr": profile["clubAbbr"],
            "personaId": int(CFG["persona_id"]),
            "personaName": profile["personaName"],
            "credits": STATE.credits(),
        })

    # Static client-side localization/config requests observed in FUT.
    if low == "/fut/loc/pc/leaderboards.eng_us.xml":
        return 404, {"Content-Type": "text/plain"}, b"not found"
    if low == "/fut/tutorials/cmn":
        return 404, {"Content-Type": "text/plain"}, b"not found"
    if low == "/fut/packs/loc/storepackdescriptions.en_us.xml":
        # FUT store pack localization is an XLIFF translation file.
        # The native client resolves the visible title/description through
        # FUT_STORE_PACK_<packId>_NAME / _DESC keys rather than from the
        # human-readable name fields in purchasegroup/all.
        settings = load_pack_settings()
        loc_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<xliff version="1.2">',
            '  <file original="storepackdescriptions" source-language="en-US" datatype="plaintext">',
            '    <body>',
        ]

        exported = []
        for pid_s, cfg in sorted(
            settings.get("packs", {}).items(),
            key=lambda kv: int(kv[0])
        ):
            if not bool(cfg.get("enabled", True)):
                continue

            try:
                pid = int(pid_s)
            except Exception:
                continue

            name = str(cfg.get("name", f"FUT Pack {pid}") or f"FUT Pack {pid}")
            bio = str(cfg.get("bio", "") or "")

            name_xml = html.escape(name, quote=False)
            bio_xml = html.escape(bio, quote=False)

            # Desktop FUT store name.
            key_name = f"FUT_STORE_PACK_{pid}_NAME"
            loc_lines.append(
                f'      <trans-unit id="{key_name}" resname="{key_name}">'
                f'<source>{name_xml}</source></trans-unit>'
            )

            # Pack detail/description panel.
            key_desc = f"FUT_STORE_PACK_{pid}_DESC"
            loc_lines.append(
                f'      <trans-unit id="{key_desc}" resname="{key_desc}">'
                f'<source>{bio_xml}</source></trans-unit>'
            )

            # FIFA web/mobile-era localization files also expose a MOBILE name.
            # Keeping it here is harmless for the PC client and improves
            # compatibility with builds that request the same key family.
            key_mobile = f"FUT_STORE_PACK_{pid}_NAME_MOBILE"
            loc_lines.append(
                f'      <trans-unit id="{key_mobile}" resname="{key_mobile}">'
                f'<source>{name_xml}</source></trans-unit>'
            )
            exported.append((pid, name, bio))

        loc_lines.extend([
            '    </body>',
            '  </file>',
            '</xliff>',
        ])
        xml = ("\n".join(loc_lines)).encode("utf-8")

        log.warning("STORE-SCOUT LOC RESPONSE xml=%s", xml.decode("utf-8", errors="replace"))
        log.info("STORE PACK LOC XLIFF packs=%s", exported)

        return 200, {
            "Content-Type": "application/xml; charset=utf-8",
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }, xml

    # Exact FIFA 15 game namespace.
    if low == "/ut/game/fifa15/settings":
        return 200, {}, json_bytes({"configs": [
            {"type": "IsStoreEnabled", "value": "1"},
            {"type": "cardPackStoreEnabled", "value": "1"},
            {"type": "pointsPackStoreEnabled", "value": "1"},
        ]})

    if low.startswith("/ut/game/fifa15/phishing/trusteddevice"):
        return 200, {}, json_bytes({
            "trusted": True, "exists": True, "locked": False, "changed": False,
            "token": "fut15-local-phishing-token", "isTrusted": True,
            "completed": True, "answerRequired": False, "attempts": 0,
        })

    if low == "/ut/game/fifa15/match/reset":
        # Retail calls this during ordinary FUT bootstrap too. Keep it a pure
        # acknowledgement; do not alter the active offline-season save.
        log.info("MATCH FLOW reset method=%s body=%s", method, payload if isinstance(payload, dict) else {})
        return 200, {}, json_bytes({"reset": True})

    # ---- FIFA 15 PC native match lifecycle -------------------------------
    # The working FIFA 14 PC Seasons build uses the same three route family:
    #   POST/PUT /match       CreateMatch / MatchReady
    #   GET      /match       status
    #   POST/PUT /match/end   DestroyMatch
    # Keep this deliberately conservative. FIFA's own season/user save blob
    # remains authoritative for round/points progression.
    if low == "/ut/game/fifa15/match":
        doc = payload if isinstance(payload, dict) else {}
        result_markers = {
            "minutesPlayed", "minutes", "matchMinutes", "goals", "goalsScored",
            "goalsFor", "homeGoals", "goalsAgainst", "goalsConceded", "awayGoals",
            "result", "completed", "matchCompleted", "finished", "dnf", "didNotFinish",
            "quit", "abandoned", "shotsOnTarget", "passAccuracy", "possession",
            "successfulTackles",
        }
        is_create = method in ("POST", "PUT") and "squadId" in doc and not any(k in doc for k in result_markers)
        is_ready = method == "PUT" and isinstance(doc.get("items"), list) and "squadId" not in doc and not any(k in doc for k in result_markers)
        if is_create or is_ready:
            STATE.set("offline_match_pending", True)
            STATE.set("offline_match_started_at", now_s())
            if is_create:
                STATE.set("offline_match_starters", [])
            elif is_ready:
                starter_ids = []
                for raw in doc.get("items", []):
                    if isinstance(raw, dict):
                        try: starter_ids.append(int(raw.get("id", raw.get("itemId", 0)) or 0))
                        except Exception: pass
                STATE.set("offline_match_starters", [x for x in starter_ids if x > 0][:11])
                log.warning("MATCH CONTRACTS starters=%s", STATE.get("offline_match_starters", []))
            st = STATE.offline_season_state()
            log.warning(
                "SEASONS MATCH %s season=10 division=%s round=%s body=%s",
                "CREATE" if is_create else "READY",
                int(st.get("division", 10) or 10),
                max(1, int(st.get("round", 0) or 0) + 1),
                doc,
            )
            return 200, {"Cache-Control": "no-store"}, json_bytes({
                "squad": _native_squad(),
                "startDateTime": now_s(),
            })
        if method == "GET":
            return 200, {"Cache-Control": "no-store"}, json_bytes({
                "match": None,
                "credits": STATE.credits(),
            })
        log.warning("MATCH FLOW generic method=%s body=%s", method, doc)
        return 200, {"Cache-Control": "no-store"}, json_bytes({})

    if low == "/ut/game/fifa15/match/end":
        doc = payload if isinstance(payload, dict) else {}
        end_reason = str(doc.get("endReason") or doc.get("result") or "NO_CONTEST").strip().upper()
        # Offline Seasons treats an in-match quit/DNF as a played loss. Returning
        # QUIT here made FIFA save the pre-match opaque SeasonData again and then
        # show Start Season on re-entry. Tell the client the terminal fixture
        # result is LOSS while still awarding zero coins for the DNF.
        response_reason = "LOSS" if end_reason in {"QUIT", "DNF", "FORFEIT"} else end_reason

        # A retry after the first terminal settlement must return the exact same
        # successful award document instead of creating a second result.
        if not bool(STATE.get("offline_match_pending", False)):
            cached = STATE.get("last_match_end_response", {})
            if isinstance(cached, dict) and cached and end_reason in {"WIN", "DRAW", "LOSS", "QUIT", "DNF", "FORFEIT"}:
                log.warning("SEASONS MATCH END retry returning cached settlement reason=%s", end_reason)
                return 200, {"Cache-Control": "no-store"}, json_bytes(cached)

        st_before = STATE.offline_season_state()
        internal_defs = _offline_season_definitions()
        current = next(
            (x for x in internal_defs if int(x.get("divisionNumber", 10)) == int(st_before.get("division", 10))),
            internal_defs[-1],
        )
        difficulty = int(current.get("difficulty", 1) or 1)

        raw_items = doc.get("items") if isinstance(doc.get("items"), list) else []
        stat_items: list[dict[str, Any]] = []
        allowed = (
            "shots", "goals", "yellowCards", "redCards", "suspension",
            "injuryType", "injuryGames", "fitness", "assists",
        )
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            try:
                iid = int(raw.get("id", raw.get("itemId", 0)) or 0)
            except Exception:
                iid = 0
            if iid <= 0:
                continue
            row: dict[str, Any] = {"id": iid}
            for key in allowed:
                if key in raw:
                    row[key] = raw.get(key)
            stat_items.append(row)

        # Fitness/stat mutations arriving with DestroyMatch are part of the
        # authoritative local club state too. Persist them before building the
        # response so a relaunch cannot restore pre-match fitness/stat values.
        for row in stat_items:
            try:
                STATE.update_item_fields(int(row.get("id", 0) or 0), row)
            except Exception:
                pass

        reward = _offline_match_reward(doc, end_reason)
        seconds_played = int(reward.get("secondsPlayed", 0) or 0)
        if end_reason in {"QUIT", "DNF", "FORFEIT"} and seconds_played <= 0:
            # A zero-second terminal response can be interpreted by the client as
            # a no-contest bootstrap instead of a played DNF. Use the measured
            # local match lifetime so a user-initiated forfeit is still a real
            # loss/fixture settlement while receiving zero coins.
            started_at = int(STATE.get("offline_match_started_at", now_s()) or now_s())
            seconds_played = max(1, now_s() - started_at)
        first_settlement = bool(STATE.get("offline_match_pending", False)) and end_reason in {
            "WIN", "DRAW", "LOSS", "QUIT", "DNF", "FORFEIT"
        }

        settled = st_before
        reward_coins = 0
        if first_settlement:
            result_key = "win" if end_reason == "WIN" else "draw" if end_reason == "DRAW" else "loss"
            mine = doc.get("myMatchStats") if isinstance(doc.get("myMatchStats"), dict) else {}
            opp = doc.get("opponentMatchStats") if isinstance(doc.get("opponentMatchStats"), dict) else {}
            gf = max(0, int(mine.get("goals", 0) or 0))
            ga = max(0, int(opp.get("goals", 0) or 0))
            settled = STATE.update_offline_season({
                "result": result_key,
                "goalsFor": int(st_before.get("goalsFor", 0) or 0) + gf,
                "goalsAgainst": int(st_before.get("goalsAgainst", 0) or 0) + ga,
            })
            record_key = "record_wins" if result_key == "win" else "record_draws" if result_key == "draw" else "record_losses"
            STATE.set(record_key, int(STATE.get(record_key, 0) or 0) + 1)
            STATE.set("offline_season_history_goals_for", int(STATE.get("offline_season_history_goals_for", 0) or 0) + gf)
            STATE.set("offline_season_history_goals_against", int(STATE.get("offline_season_history_goals_against", 0) or 0) + ga)

            # Completed matches receive the award exactly once. Quit/DNF remains
            # zero so the local economy cannot be farmed through forfeits.
            if end_reason in {"WIN", "DRAW", "LOSS"}:
                reward_coins = int(reward.get("rewardCoins", 0) or 0)
                if reward_coins > 0:
                    STATE.add_credits(reward_coins)
                    STATE.set("offline_season_coins", int(STATE.get("offline_season_coins", 0) or 0) + reward_coins)

            # FUT contracts are consumed by players who actually took part in the
            # fixture. Start with the 11 MatchReady starters, then include any bench
            # item that appears to have entered play (fitness/stat mutation). This is
            # performed only on the first terminal settlement, so retries cannot
            # consume a second contract.
            participant_ids = set(int(x) for x in (STATE.get("offline_match_starters", []) or []) if int(x or 0) > 0)
            for row in stat_items:
                iid = int(row.get("id", 0) or 0)
                if iid <= 0 or iid in participant_ids:
                    continue
                if int(row.get("fitness", 99) or 99) < 99 or any(int(row.get(k, 0) or 0) for k in ("goals","assists","shots","yellowCards","redCards")):
                    participant_ids.add(iid)
            contract_updates = STATE.decrement_player_contracts(sorted(participant_ids))
            STATE.set("offline_match_starters", [])
            log.warning("MATCH CONTRACTS decremented=%s", [(int(x.get("id",0)), int(x.get("contract",0))) for x in contract_updates])

            # Player/GK training cards are one-match effects. Expire only after
            # the first terminal settlement so retries cannot consume/restore twice.
            expired_training = STATE.expire_training_for_items([int(x.get("id", 0) or 0) for x in stat_items])

            # FIFA writes its native SeasonData envelope immediately after
            # /match/end. For quit/DNF we now return LOSS, which makes the client
            # author a real next-round blob instead of echoing its pre-match save.
            STATE.set("awaiting_post_match_season_save", True)

            log.warning(
                "SEASONS PROGRESSION settled result=%s reward=%s state=%s record=%s-%s-%s",
                result_key, reward_coins, settled,
                int(STATE.get("record_wins", 0) or 0),
                int(STATE.get("record_draws", 0) or 0),
                int(STATE.get("record_losses", 0) or 0),
            )

        current_credits = STATE.credits()
        response: dict[str, Any] = {
            "endReason": response_reason,
            "secondsPlayed": seconds_played,
            "matchDifficulty": difficulty,
            "items": stat_items,
            "matchData": str(doc.get("matchData") or ""),
            "credits": current_credits,
            "coins": current_credits,
        }

        if end_reason in {"WIN", "DRAW", "LOSS", "QUIT", "DNF", "FORFEIT"}:
            completed_normally = end_reason in {"WIN", "DRAW", "LOSS"}
            # FIFA 15 PC's RS4:FutDestroyMatchServerResponse does NOT consume
            # our earlier completionAward/skillAward/rewardCoins names.  The
            # retail decoder reads allCoins, matchCoins, participationAward,
            # gameModeAward, boostConis (the retail typo), and the multiplier/
            # partial arrays.  Keep the old aliases for diagnostics, but make
            # the native fields authoritative so the post-match award screen
            # can actually render the coins that were already credited locally.
            native_total = int(reward_coins if first_settlement else reward.get("totalCoins", 0) or 0) if completed_normally else 0
            native_participation = int(reward.get("completionAward", 0) or 0) if completed_normally else 0
            native_match = max(0, native_total - native_participation) if completed_normally else 0
            response.update({
                "allCoins": native_total,
                "matchCoins": native_match,
                "participationAward": native_participation,
                "gameModeAward": {"coins": 0},
                "boostConis": 0,
                "boostCountLeft": 0,
                "matchCoinMultipliers": [],
                "matchCoinPartials": [],
                "seasonCoins": 0,
                "tournamentCoins": 0,
                "teamOfTournamentWinner": False,

                # Legacy/local aliases retained so old traces and cached
                # settlements stay easy to inspect.
                "completionAward": native_participation,
                "skillAward": native_match,
                "rewardCoins": native_total,
                "totalCoins": native_total,
                "dnfModifier": float(reward.get("dnfModifier", 1.0) or 1.0),
                "seasonId": 10,
                "divisionId": int(settled.get("division", 10) or 10),
                "seasonRound": max(1, int(settled.get("round", 0) or 0) + 1),
                "seasonPoints": int(settled.get("points", 0) or 0),
                "seasonGamesWon": int(settled.get("wins", 0) or 0),
                "seasonGamesDraw": int(settled.get("draws", 0) or 0),
                "seasonGamesLost": int(settled.get("losses", 0) or 0),
            })
        if first_settlement:
            refreshed = []
            for row in stat_items:
                item = STATE.get_item(int(row.get("id", 0) or 0))
                if item and str(item.get("itemType", "player")) == "player":
                    refreshed.append(_native_player_item(item))
            if refreshed:
                response["itemData"] = refreshed

        if isinstance(doc.get("myMatchStats"), dict):
            response["myMatchStats"] = doc["myMatchStats"]
        if isinstance(doc.get("opponentMatchStats"), dict):
            response["opponentMatchStats"] = doc["opponentMatchStats"]

        if first_settlement:
            STATE.set("offline_match_pending", False)
            STATE.set("last_match_end_response", response)

        if end_reason in {"WIN", "DRAW", "LOSS", "QUIT", "DNF", "FORFEIT"}:
            log.warning(
                "MATCH REWARD FIFA15-NATIVE allCoins=%s matchCoins=%s participationAward=%s wallet=%s",
                int(response.get("allCoins", 0) or 0),
                int(response.get("matchCoins", 0) or 0),
                int(response.get("participationAward", 0) or 0),
                current_credits,
            )

        log.warning(
            "SEASONS MATCH END season=10 division=%s round=%s reason=%s body=%s response=%s",
            int(st_before.get("division", 10) or 10),
            max(1, int(st_before.get("round", 0) or 0) + 1),
            end_reason,
            doc,
            response,
        )
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    if low == "/ut/game/fifa15/user":
        return 200, {}, json_bytes(_native_user())

    if low == "/ut/game/fifa15/userdata":
        return 200, {}, json_bytes({"onlineELORating": 0, "onlineRatedUser": False, "accountResetCount": 0})

    if low == "/ut/v2/game/fifa15/store/transaction":
        return 200, {}, json_bytes({"state": "NOTRANSACTION"})

    if low == "/ut/game/fifa15/clientdata/tutorialpopups":
        return 200, {}, json_bytes({"entries": []})
    if low == "/ut/game/fifa15/clientdata/pilesize":
        return 200, {}, json_bytes({"entries": [{"key": 2, "value": 100}, {"key": 4, "value": 100}]})
    if low == "/ut/game/fifa15/clientdata/userhubdata":
        return 200, {}, json_bytes({"entries": [{"key": 0, "value": 13}, {"key": 1, "value": 12}]})
    if low == "/ut/game/fifa15/clientdata/managerquest":
        return 200, {}, json_bytes({"entries": [{"key": 0, "value": 148528}, {"key": 1, "value": 148528}, {"key": 2, "value": 0}]})
    if low == "/ut/game/fifa15/clientdata/loanplayerreward":
        return 200, {}, json_bytes({"entries": []})

    if low == "/ut/game/fifa15/loan/players":
        return 200, {}, json_bytes({"loans": []})

    if low == "/ut/game/fifa15/squad/active" and method == "GET":
        return 200, {"Cache-Control": "no-store"}, json_bytes(_native_squad())

    if low == "/ut/game/fifa15/squad/list" and method == "GET":
        response = _native_squad_list()
        log.warning("SQUAD LIST active=%s ids=%s", response.get("activeSquadId"), [x.get("id") for x in response.get("squad", [])])
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    if low == "/ut/game/fifa15/squad" and method == "GET":
        return 200, {"Cache-Control": "no-store"}, json_bytes(_native_squad_list())

    if low == "/ut/game/fifa15/squad" and method == "POST":
        created = STATE.create_squad(payload if isinstance(payload, dict) else {})
        return 200, {"Cache-Control": "no-store"}, json_bytes(_native_squad(int(created.get("id", 0) or 0)))

    if low == "/ut/game/fifa15/squad/clone" and method == "POST":
        src = dict(payload) if isinstance(payload, dict) else {}
        source_id = int(src.get("srcId", src.get("id", 0)) or 0)
        name = str(src.get("dstSquadName", src.get("squadName", "")) or "")
        cloned = STATE.clone_squad(source_id, name)
        if not cloned:
            return 404, {"Cache-Control": "no-store"}, json_bytes({"error": "squad not found"})
        return 200, {"Cache-Control": "no-store"}, json_bytes(_native_squad(int(cloned.get("id", 0) or 0)))

    squad_id_match = re.match(r"^/ut/game/fifa15/squad/(\d+)$", low)
    if squad_id_match:
        sid = int(squad_id_match.group(1))
        if method == "GET":
            return 200, {"Cache-Control": "no-store"}, json_bytes(_native_squad(sid))
        if method == "DELETE":
            ok = STATE.delete_squad(sid)
            log.warning("SQUAD DELETE sid=%s success=%s", sid, ok)
            return 200, {"Cache-Control": "no-store"}, b""
        if method in ("PUT", "POST"):
            src = dict(payload) if isinstance(payload, dict) else {}
            src["id"] = sid
            saved = STATE.save_squad(src)
            log.warning("SQUAD HTTP SAVE sid=%s keys=%s playersInRequest=%s", sid, sorted(src.keys()), len(src.get("players", [])) if isinstance(src.get("players"), list) else None)
            return 200, {"Cache-Control": "no-store"}, json_bytes(_native_squad(int(saved.get("id", sid) or sid)))

    if low == "/ut/game/fifa15/eventfeed":
        return 200, {}, json_bytes({"event": [], "timestamp": now_s()})

    if low == "/ut/game/fifa15/hub":
        user_auctions = STATE.list_user_auctions()
        selling = sum(1 for x in user_auctions if str(x.get("state")) == "active")
        sold = sum(1 for x in user_auctions if str(x.get("state")) == "sold")
        ai_live = _market_live_count()
        return 200, {}, json_bytes({
            "auctionCount": ai_live + selling,
            "liveTransfers": ai_live + selling,
            "clubPlayers": len(STATE.list_items("club")) + len(STATE.list_items("squad")),
            "tradePile": {"count": STATE.transfer_list_count(), "selling": selling, "sold": sold, "maximum": 100},
            "watchlist": {"count": 0, "outbid": 0, "winning": 0},
            "squad": _native_squad(),
        })

    if low == "/ut/game/fifa15/clubuser":
        # CardsDLL uses clubUser as a face-card/apply-consumable cache bootstrap.
        # Return the owned player page plus every owned consumable so opening
        # Apply Consumable on a squad player has the card definitions available.
        players = [
            x for x in (STATE.list_items("club") + STATE.list_items("squad"))
            if str(x.get("itemType", "player")) == "player"
        ]
        players.sort(key=lambda x: (
            -int(x.get("rating", 0) or 0), -int(x.get("rareflag", 0) or 0),
            int(x.get("id", 0) or 0)
        ))
        consumables = [
            x for x in STATE.list_items("club")
            if str(x.get("itemType", "player")) != "player"
            and int(x.get("resourceId", 0) or 0) in CONSUMABLE_BY_RESOURCE
        ]
        player_wire = [_native_player_item(x) for x in players[:50]]
        consumable_wire = [_native_consumable_item(x, pile=7) for x in consumables]
        preload = player_wire + consumable_wire
        log.warning(
            "CLUBUSER CACHE native players=%s consumables=%s total=%s consumableFamilies=%s",
            len(player_wire), len(consumable_wire), len(preload),
            sorted({_consumable_family_from_item(x) for x in consumables}),
        )
        return 200, {"Cache-Control": "no-store"}, json_bytes({
            "user": [{
                "persona": str(_persona_name()),
                "personaId": int(CFG["persona_id"]),
                "public": True,
            }],
            "itemData": preload,
            "total": len(players) + len(consumables),
            "count": len(preload),
            "start": 0,
        })

    if low == "/ut/game/fifa15/leaderboards/options":
        return 200, {}, json_bytes({})

    if low.startswith("/ut/game/fifa15/club/consumables"):
        stored = [x for x in STATE.list_items("club") if str(x.get("itemType", "player")) != "player"]
        suffix = low.rsplit("/", 1)[-1].replace("_", "").replace("-", "").lower()
        requested = str(query.get("category", query.get("type", [""]))[0] or "").replace("_", "").replace("-", "").lower()

        aliases = {
            "contract": "contracts", "contracts": "contracts",
            "managercontract": "managercontracts", "managercontracts": "managercontracts",
            "fitness": "fitness", "healing": "healing",
            "training": "training", "development": "development",
            "playstyle": "playstyle", "chemistry": "playstyle", "chemistrystyle": "playstyle",
            "position": "position", "positioning": "position",
            "managerleague": "managerleague", "league": "managerleague",
        }
        family = aliases.get(suffix if suffix not in ("consumables", "club") else requested,
                             suffix if suffix not in ("consumables", "club") else requested)

        if family and family != "development":
            stored = [x for x in stored if _consumable_family_from_item(x) == family]
        elif family == "development":
            # FIFA 15 distinguishes development and training on the wire.  The
            # old umbrella response mixed manager league/training/contracts in
            # one result and defeated the client's own subtype filter.
            stored = [x for x in stored if
                      int(x.get("resourceId", 0) or 0) in CONSUMABLE_BY_RESOURCE
                      and str(CONSUMABLE_BY_RESOURCE[int(x.get("resourceId", 0) or 0)].get("itemType", "development")).lower() == "development"]

        grouped: dict[int, dict[str, Any]] = {}
        for item in stored:
            rid = int(item.get("resourceId", 0) or 0)
            if not rid:
                continue
            definition = CONSUMABLE_BY_RESOURCE.get(rid, {})
            row = grouped.get(rid)
            if row is None:
                row = _native_consumable_item(item, pile=7)
                row["count"] = 0
                row["untradeableCount"] = 0
                grouped[rid] = row
            row["count"] += 1
            if bool(item.get("untradeable", False)):
                row["untradeableCount"] += 1
        rows = list(grouped.values())
        rows.sort(key=lambda x: (
            -int(x.get("rating", 0) or 0), -int(x.get("rareflag", 0) or 0),
            int(x.get("resourceId", 0) or 0)
        ))
        log.warning(
            "CLUB CONSUMABLE SEARCH family=%s total=%s categories=%s resources=%s",
            family or "all", len(rows),
            sorted({str(x.get("category", "")) for x in rows}),
            [int(x.get("resourceId", 0) or 0) for x in rows[:20]],
        )
        return 200, {"Cache-Control": "no-store"}, json_bytes({
            "item": rows, "items": rows, "itemData": rows,
            "total": len(rows), "count": len(rows), "start": 0,
        })

    if low == "/ut/game/fifa15/club/stats/consumables":
        return 200, {"Cache-Control": "no-store"}, json_bytes(_consumable_stats())

    if low.startswith("/ut/game/fifa15/club/stats/"):
        return 200, {}, json_bytes(_club_stats())

    if low == "/ut/game/fifa15/club":
        requested_type = str(query.get("type", [""])[0] or "").lower()
        # Player searches must include cards currently fielded by the active
        # squad. FIFA still shows them in My Club position filters.
        if requested_type == "player":
            items = [x for x in (STATE.list_items("club") + STATE.list_items("squad"))
                     if str(x.get("itemType", "player")) == "player"]
        else:
            items = STATE.list_items("club")

        if requested_type in ("consumable", "development", "training"):
            items = [x for x in items if int(x.get("resourceId", 0) or 0) in CONSUMABLE_BY_RESOURCE]
        elif requested_type == "manager":
            items = [x for x in items if str(x.get("itemType", "")).lower() == "manager"]
        elif requested_type in ("kit", "stadium", "ball", "custom", "badge", "trophy"):
            wanted = "custom" if requested_type == "badge" else requested_type
            items = [x for x in items if str(x.get("itemType", "")).lower() == wanted]
        elif requested_type == "equippables":
            items = [x for x in items if str(x.get("itemType", "")).lower() in {"kit", "stadium", "ball", "custom"}]
        elif requested_type and requested_type not in ("any", "-1"):
            items = [x for x in items if str(x.get("itemType", "")).lower() == requested_type]

        def _qint(name: str, default: int = -1) -> int:
            try:
                return int(query.get(name, [default])[0])
            except Exception:
                return default

        # Native My Club filters. v0.2.16 parsed none of these, so selecting CM,
        # LB, nation, league, etc. merely paged the same complete player list.
        if requested_type == "player":
            position = str(query.get("position", query.get("pos", [""]))[0] or "").upper()
            nation = _qint("nation", -1)
            league = _qint("league", -1)
            team = _qint("team", -1)
            level = str(query.get("level", ["any"])[0] or "any").lower()
            filtered: list[dict[str, Any]] = []
            for item in items:
                pos = str(item.get("preferredPosition", "") or "").upper()
                rating = int(item.get("rating", 0) or 0)
                rareflag = int(item.get("rareflag", 0) or 0)
                special = rareflag > 1
                if position not in ("", "ANY", "-1") and pos != position:
                    continue
                if nation >= 0 and int(item.get("nation", -1) or -1) != nation:
                    continue
                if league >= 0 and int(item.get("leagueId", -1) or -1) != league:
                    continue
                if team >= 0 and int(item.get("teamid", item.get("teamId", -1)) or -1) != team:
                    continue
                if level not in ("", "any", "-1"):
                    if level == "bronze" and not (rating <= 64 and not special): continue
                    if level == "silver" and not (65 <= rating <= 74 and not special): continue
                    if level == "gold" and not (rating >= 75 and not special): continue
                    if level in ("sp", "special") and not special: continue
                filtered.append(item)
            items = filtered

        def _club_sort_key(item):
            try: rating = int(item.get("rating", 0) or 0)
            except Exception: rating = 0
            try: rareflag = int(item.get("rareflag", 0) or 0)
            except Exception: rareflag = 0
            try: rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
            except Exception: rid = 0
            try: iid = int(item.get("id", 0) or 0)
            except Exception: iid = 0
            return (-rating, -rareflag, -rid, iid)

        items = sorted(items, key=_club_sort_key)
        try:
            count = int(query.get("count", [len(items)])[0] or len(items))
        except Exception:
            count = len(items)
        start = 0
        for key in ("start", "offset", "startIndex", "startindex"):
            if key in query:
                try:
                    start = max(0, int(query.get(key, [0])[0] or 0))
                    break
                except Exception:
                    pass
        if start == 0 and "page" in query:
            try:
                page = max(1, int(query.get("page", [1])[0] or 1))
                start = (page - 1) * max(1, count)
            except Exception:
                pass
        page_items = items[start:start + max(0, count)]

        all_club = STATE.list_items("club")
        all_squad = STATE.list_items("squad")
        all_players = [x for x in all_club + all_squad if str(x.get("itemType", "player")) == "player"]
        all_consumables = [x for x in all_club if int(x.get("resourceId", 0) or 0) in CONSUMABLE_BY_RESOURCE]
        all_cosmetics = [x for x in all_club if str(x.get("itemType", "")).lower() in {"kit","stadium","ball","custom"}]
        log.info(
            "CLUB PAGE start=%d count=%d total=%d returned=%d query=%s positions=%s",
            start, count, len(items), len(page_items), query,
            sorted({str(x.get('preferredPosition','')) for x in page_items if str(x.get('itemType','player')) == 'player'}),
        )
        return 200, {}, json_bytes({
            "pileClubPlayers": len([x for x in all_players if str(x.get("pile", "club")) == "club"]),
            "pileSquadPlayers": len([x for x in all_players if str(x.get("pile", "club")) == "squad"]),
            "pileConsumables": len(all_consumables),
            "pileManagers": len([x for x in all_club if str(x.get("itemType", "")).lower() == "manager"]),
            "pileClubItems": len(all_cosmetics),
            "pileClubTotal": len(all_club) + len(all_squad),
            "pilePack": len(STATE.list_items("unassigned")),
            "kitCount": len([x for x in all_cosmetics if x.get("itemType") == "kit"]),
            "badgeCount": len([x for x in all_cosmetics if x.get("itemType") == "custom"]),
            "stadiumCount": len([x for x in all_cosmetics if x.get("itemType") == "stadium"]),
            "ballCount": len([x for x in all_cosmetics if x.get("itemType") == "ball"]),
            "clubPlayers": len(all_players),
            "clubItemCount": len(all_club) + len(all_squad),
            "clubCount": len(all_club) + len(all_squad),
            "total": len(items),
            "count": len(page_items),
            "start": start,
            "itemData": page_items,
        })

    m_identity = re.fullmatch(r"/ut/game/fifa15/item/(\d+)", low)
    if m_identity and method in ("PUT", "POST"):
        iid = int(m_identity.group(1))
        existing = STATE.get_item(iid)
        if existing and str(existing.get("itemType", "")).lower() in {"kit","stadium","custom","ball"}:
            equipped = STATE.equip_club_item(iid)
            if equipped:
                return 200, {"Cache-Control":"no-store"}, json_bytes({"itemData":[equipped], "actives":_active_club_items()})

    if low == "/ut/game/fifa15/user/credits":
        return 200, {}, json_bytes(_credits_payload())

    if low in ("/ut/game/fifa15/store/purchasegroup/all", "/ut/game/fifa15/store/purchasegroup/cardpack"):
        store_payload = _store_purchasegroups()
        log.warning("STORE-SCOUT PURCHASEGROUP RESPONSE route=%s promo=%d categories=%s %s",
                    low,
                    sum(1 for x in store_payload.get("purchase", []) if str(x.get("category")) == "promo"),
                    [x.get("value") for x in store_payload.get("categoryInfo", [])],
                    json.dumps(store_payload, ensure_ascii=False))
        return 200, {"Cache-Control": "no-store"}, json_bytes(store_payload)

    if low == "/ut/game/fifa15/purchased/items":
        if method == "POST":
            pack_id = int(payload.get("packId", 3)) if isinstance(payload, dict) else 3
            price = max(0, int(get_pack_cfg(pack_id).get("price", 0)))
            if isinstance(payload, dict) and int(payload.get("useCredits", 1)):
                if STATE.credits() < price:
                    return 200, {}, json_bytes({"duplicateItemIdList": [], "itemData": [], **_credits_payload()})
                STATE.add_credits(-price)
            log.warning("CARDS-SCOUT PACK_OPEN_BEGIN packId=%s ownedClub=%d ownedSquad=%d",
                        pack_id, len(STATE.list_items("club")), len(STATE.list_items("squad")))
            pack = STATE.create_pack(pack_id)
            log.warning("CARDS-SCOUT PACK_OPEN_ITEMS ids=%s resources=%s duplicates=%s",
                        [x.get("id") for x in pack.get("itemData", [])],
                        [x.get("resourceId") for x in pack.get("itemData", [])],
                        pack.get("duplicateItemIdList", []))
            # FIFA's native pack-purchase response uses itemList as the ordered
            # reveal list.  Do not also send itemData/items here: those extra
            # aliases caused the PC client to rebuild the collection and fall
            # back to its resourceId ordering instead of our reveal order.
            ordered_pack_items = [_native_pack_item(x) for x in pack.get("itemData", [])]
            real_resources = [x.get("resourceId") for x in ordered_pack_items]
            ordered_pack_items = [_display_sort_alias(x, i) for i, x in enumerate(ordered_pack_items)]
            log.warning("PACK DISPLAY ORDER ratings=%s rareflags=%s ids=%s timestamps=%s realResources=%s aliasResources=%s",
                        [x.get("rating") for x in ordered_pack_items],
                        [x.get("rareflag") for x in ordered_pack_items],
                        [x.get("id") for x in ordered_pack_items],
                        [x.get("timestamp") for x in ordered_pack_items],
                        real_resources,
                        [x.get("resourceId") for x in ordered_pack_items])
            return 200, {}, json_bytes({
                "numberItems": int(pack.get("numberItems", len(ordered_pack_items))),
                "purchasedPackId": int(pack.get("purchasedPackId", pack_id)),
                "duplicateItemIdList": pack["duplicateItemIdList"],
                # Feed the same desired order through every FIFA 15 response alias.
                "itemList": ordered_pack_items,
                "itemData": ordered_pack_items,
                "items": ordered_pack_items,
                **_credits_payload(),
            })
        # When there are unassigned pack cards, preserve their duplicate markers on
        # refreshes of purchased/items. With no unassigned cards this stays exactly
        # the normal empty bootstrap shape used while entering FUT.
        unassigned = STATE.list_items("unassigned")

        # FIFA refreshes /purchased/items after the pack-open POST and uses this
        # refreshed itemData order for the reveal/New Items screen. Keep this
        # order identical to create_pack(): highest rating first.
        def _unassigned_reveal_sort_key(item):
            try:
                rating = int(item.get("rating", 0) or 0)
            except Exception:
                rating = 0
            try:
                rareflag = int(item.get("rareflag", 0) or 0)
            except Exception:
                rareflag = 0
            try:
                rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
            except Exception:
                rid = 0
            # Same ordering as create_pack(): specials first, then OVR descending.
            is_special = bool(item.get("special", False)) or rareflag > 1
            return (0 if is_special else 1, -rating, -rareflag, -rid)

        unassigned = sorted(unassigned, key=_unassigned_reveal_sort_key)

        duplicate_item_list = []
        for item in unassigned:
            try:
                iid = int(item.get("id", 0) or 0)
                rid = int(item.get("resourceId", item.get("assetId", 0)) or 0)
            except Exception:
                continue
            owned_item = STATE.owned_player_item_by_resource_id(rid)
            owned_iid = int(owned_item.get("id", 0) or 0) if isinstance(owned_item, dict) else 0
            if iid and owned_iid:
                duplicate_item_list.append({"itemId": iid, "duplicateItemId": owned_iid})
        native_unassigned = [_native_pack_item(x) for x in unassigned]
        real_resources = [x.get("resourceId") for x in native_unassigned]
        # Pack reveals use a response-only resourceId alias to control carousel order.
        # A market purchase must NEVER use that alias: the search/Assign Now screen
        # resolves the card art from the real special resourceId. Aliasing IF Rooney
        # (67162914), for example, turned him into an undefined NOT FOUND card.
        is_market_purchase = any(int(x.get("lastSalePrice", 0) or 0) > 0 for x in unassigned)
        if not is_market_purchase:
            native_unassigned = [_display_sort_alias(x, i) for i, x in enumerate(native_unassigned)]
        log.warning("UNASSIGNED DISPLAY ORDER source=%s ratings=%s rareflags=%s realResources=%s responseResources=%s",
                    "market" if is_market_purchase else "pack",
                    [x.get("rating") for x in native_unassigned],
                    [x.get("rareflag") for x in native_unassigned],
                    real_resources,
                    [x.get("resourceId") for x in native_unassigned])
        return 200, {}, json_bytes({
            "numberItems": len(native_unassigned),
            "duplicateItemIdList": duplicate_item_list,
            "itemData": native_unassigned,
        })

    # ---- Local AI Transfer Market ---------------------------------------
    if low == "/ut/game/fifa15/watchlist":
        # FIFA polls this when moving from search results to Transfer Targets.
        # Bidding persistence comes later; an explicit native-shaped empty list
        # is better than letting it fall into the generic unknown-route handler.
        if method == "GET":
            return 200, {}, json_bytes({
                "auctionInfo": [], "itemData": [], "total": 0, "count": 0,
                "winning": 0, "outbid": 0, "credits": STATE.credits(),
            })
        if method in ("POST", "PUT", "DELETE"):
            return 200, {}, json_bytes({"success": True, "auctionInfo": [], "credits": STATE.credits()})

    if low == "/ut/game/fifa15/transfermarket" and method == "GET":
        if bool(CFG.get("ai_market_enabled", True)):
            results, total = _market_search(query)
        else:
            results, total = [], 0
        log.info("AI MARKET search query=%s results=%d total=%d", query, len(results), total)
        return 200, {}, json_bytes({"auctionInfo": results, "total": total, "count": total, "credits": STATE.credits()})

    if low in (
        "/ut/game/fifa15/tradepile/counts",
        "/ut/game/fifa15/auctionhouse/counts",
    ):
        # CardsDLL's GetAuctionCount / GetAuctionLimitInfo contract.  This is
        # *owner auction capacity*, not the size of the global AI market.  The
        # earlier builds accidentally exposed the 170k+ synthetic market count
        # here (or, for the retail /tradePile/counts route, fell through to an
        # empty unknown response).  The Transfer List UI can render an inactive
        # item in either case, but ConfirmAuctionCount then refuses to open the
        # List-on-Market form because current>=maximum / maximum defaults to 0.
        auctions = STATE.list_user_auctions()
        active = sum(1 for x in auctions if str(x.get("state")) == "active")
        sold = sum(1 for x in auctions if str(x.get("state")) == "sold")
        total_pile = STATE.transfer_list_count()
        ai_live = _market_live_count()
        response = {
            "auctionCount": active,
            "maxAuctionsAllowed": 100,
            # Retail/compat aliases used by adjacent transfer-list binders.
            "currentTradePileSize": total_pile,
            "maximumTradePileSize": 100,
            "tradePileCount": total_pile,
            "transferListCount": total_pile,
            "selling": active,
            "sold": sold,
            # Keep the global market number separate so the Transfers hub can
            # still advertise the populated local AI market without poisoning
            # the user's auction-capacity check.
            "liveTransfers": ai_live + active,
        }
        log.warning(
            "AUCTION LIMITS route=%s current=%s max=%s transferList=%s sold=%s globalLive=%s",
            low, active, response["maxAuctionsAllowed"], total_pile, sold, response["liveTransfers"],
        )
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    if low in (
        "/ut/game/fifa15/auctionhouse/pricelimits",
        "/ut/game/fifa15/marketdata/pricelimits",
        "/ut/game/fifa15/marketdata/item/pricelimits",
    ):
        # Native FIFA 15 suggested-pricing contract.  The retail CardsDLL parser
        # names only these fields for this response: marketData ->
        # marketPriceLimitValues[] -> maskDefId/minPrice/maxPrice.  Earlier local
        # builds returned a large compatibility object and incorrectly used the
        # response-only sortable defId as maskDefId; the client accepted HTTP 200
        # but never unlocked the Start Price/BIN form.
        requested_def = _query_int(
            query,
            ("resourceId", "resourceid", "definitionId", "definitionid", "defId", "defid"),
            0,
        )
        rid = int(requested_def or 0)
        iid = _query_int(query, ("itemId", "itemid", "itemIdList", "itemidlist"), 0)
        if iid:
            item = STATE.get_item(iid)
            if item:
                rid = int(item.get("resourceId", item.get("assetId", rid)) or rid)

        # Pack-result cards are displayed with a sortable alias whose high byte
        # encodes carousel order (e.g. 0x01xxxxxx), while the owned special item
        # retains the real special resource id (e.g. 0x04xxxxxx).  Resolve the
        # owned definition for pricing, but mask the definition for the response.
        if rid:
            base_asset = int(rid) & 0x00FFFFFF
            candidates = []
            for owned in STATE.list_items():
                if str(owned.get("itemType", "player")) != "player":
                    continue
                try:
                    owned_asset = int(owned.get("assetId", 0) or 0) & 0x00FFFFFF
                    owned_rid = int(owned.get("resourceId", 0) or 0)
                    owned_id = int(owned.get("id", 0) or 0)
                except Exception:
                    continue
                if owned_asset == base_asset and owned_rid in PLAYER_DB:
                    candidates.append((owned_id, owned_rid))
            if candidates:
                candidates.sort(reverse=True)
                rid = int(candidates[0][1])

        guide = STATE.market_reference_price(rid) if rid in PLAYER_DB else 1000

        def _snap_market_price(value: float) -> int:
            v = max(150, int(value))
            if v <= 1000:
                step = 50
            elif v <= 10000:
                step = 100
            elif v <= 50000:
                step = 250
            elif v <= 100000:
                step = 500
            else:
                step = 1000
            return max(150, int(round(v / step) * step))

        min_price = _snap_market_price(guide * 0.65)
        max_price = min(15000000, max(min_price, _snap_market_price(guide * 1.75)))

        # FIFA's client-side MarketDataDelegate expects this endpoint to return
        # a *root JSON array*.  On success it runs response.forEach(...) and reads
        # data.defId/data.minPrice/data.maxPrice.  Returning an object (even one
        # with otherwise plausible marketData/marketPriceLimitValues fields)
        # leaves the client-side listing workflow waiting forever.
        #
        # Echo the exact definition identity requested by the client.  The server
        # may resolve that alias to the real special-card resource ID internally
        # for valuation, but the response must correlate to the client's defId.
        response_def = int(requested_def or rid or 0)
        response = [{
            "defId": response_def,
            "minPrice": int(min_price),
            "maxPrice": int(max_price),
        }]
        # The /marketdata/item/pricelimits variant normally correlates by itemId.
        # Include it only when the client supplied an item id, while keeping the
        # same array contract and harmless defId compatibility field.
        if low.endswith("/item/pricelimits") and iid:
            response[0]["itemId"] = int(iid)
        log.warning(
            "AI MARKET PRICE LIMITS route=%s requestedDef=%s resolvedRid=%s guide=%s min=%s max=%s shape=client-root-array",
            low, requested_def, rid, guide, min_price, max_price,
        )
        log.warning("AI MARKET PRICE LIMITS RESPONSE %s", json.dumps(response, separators=(",", ":")))
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    if low == "/ut/game/fifa15/auctionhouse" and method == "POST":
        src = payload if isinstance(payload, dict) else {}
        raw_item_src = src.get("itemData", {})
        if isinstance(raw_item_src, list):
            item_src = raw_item_src[0] if raw_item_src and isinstance(raw_item_src[0], dict) else {}
        elif isinstance(raw_item_src, dict):
            item_src = raw_item_src
        else:
            item_src = {}
        try:
            item_id = int(src.get("itemId") or src.get("id") or item_src.get("id") or item_src.get("itemId") or 0)
        except Exception:
            item_id = 0
        try:
            starting = max(150, int(src.get("startingBid") or src.get("startingbid") or 150))
        except Exception:
            starting = 150
        try:
            buy_now = max(starting, int(src.get("buyNowPrice") or src.get("buyNow") or src.get("buyitnow") or starting))
        except Exception:
            buy_now = starting
        try:
            duration = max(60, int(src.get("duration") or src.get("expires") or 3600))
        except Exception:
            duration = 3600
        log.warning(
            "AI MARKET LIST REQUEST item=%s start=%s bin=%s duration=%s body=%s",
            item_id, starting, buy_now, duration, src,
        )
        auction = STATE.create_user_auction(item_id, starting, buy_now, duration)
        if not auction:
            return 200, {}, json_bytes({"auctionInfo": [], "error": "INVALID_ITEM", "credits": STATE.credits()})
        trade_id = int(auction.get("trade_id", 0) or 0)
        return 200, {}, json_bytes({
            "id": trade_id, "idStr": str(trade_id),
            "auctionInfo": [_user_auction_payload(auction)],
            "credits": STATE.credits(),
        })

    native_offer = re.match(r"^/ut/game/fifa15/trade/(\d+)/(?:offer|bid)$", low)
    auction_bid = re.match(r"^/ut/game/fifa15/auctionhouse/(\d+)/bid$", low)
    offer_match = native_offer or auction_bid
    if offer_match and method in ("PUT", "POST"):
        trade_id = int(offer_match.group(1))
        decoded = _market_decode_ai_trade(trade_id)
        if not decoded:
            return 200, {}, json_bytes({"auctionInfo": [], "error": "TRADE_NOT_FOUND", **_credits_payload()})
        rid, slot = decoded
        listing = _market_listing_for_resource(rid, slot)
        src = payload if isinstance(payload, dict) else {}
        amount = int(src.get("bid") or src.get("bidAmount") or src.get("buyNowPrice") or src.get("price") or 0)
        buy_now = int(listing.get("buyNowPrice", 0) or 0)

        if amount >= buy_now and buy_now > 0:
            if STATE.credits() < buy_now:
                return 200, {}, json_bytes({"auctionInfo": [listing], "error": "INSUFFICIENT_FUNDS", **_credits_payload()})

            # Commit the transaction before replying. FIFA immediately refreshes
            # credits + Purchased Items after /trade/<id>/offer.
            STATE.add_credits(-buy_now)
            item = STATE.make_player_item(rid, "unassigned")
            item["lastSalePrice"] = buy_now
            with STATE.lock:
                STATE.conn.execute("UPDATE items SET data=? WHERE id=?", (json.dumps(item), int(item["id"])))
                STATE.conn.commit()
            native_item = _native_player_item(item)
            native_item["pile"] = "purchased"
            # Keep the exact listing item identity in auctionInfo. FIFA's live
            # search carousel already owns that item id; replacing it with the
            # newly-created Purchased Items id makes the just-bought card redraw
            # as the white "undefined / NOT FOUND" placeholder while the success
            # modal is on screen. The persistent purchased instance is returned
            # separately below and by /purchased/items.
            sold = dict(listing)
            sold.update({
                "tradeState": "closed", "bidState": "buyNow",
                "currentBid": buy_now, "offers": 1, "expires": 0,
                "itemData": dict(listing.get("itemData") or {}),
            })

            duplicate_ids = []
            for owned in STATE.list_items("club") + STATE.list_items("squad"):
                if int(owned.get("id", 0) or 0) == int(item["id"]):
                    continue
                if str(owned.get("itemType", "player")) == "player" and int(owned.get("resourceId", 0) or 0) == rid:
                    duplicate_ids.append({"itemId": int(item["id"]), "duplicateItemId": int(owned.get("id", 0) or 0)})
                    break
            if duplicate_ids:
                STATE.mark_item_duplicate(int(item["id"]), True)
                refreshed = STATE.get_item(int(item["id"])) or item
                native_item = _native_player_item(refreshed)
                native_item["pile"] = "purchased"
                # Do not mutate sold["itemData"]: the live-search listing must
                # keep its original item id even when the purchased copy is a duplicate.

            # Preserve the CLOSED auction for the native status poll that follows
            # every successful Buy Now. Without this, deterministic AI listings
            # regenerate as ACTIVE and FIFA can leave the market transaction latched.
            _RECENT_AI_TRADE_STATUS[trade_id] = {
                "created": now_s(),
                "auction": sold,
                "duplicateItemIdList": list(duplicate_ids),
                "purchasedItemId": int(item.get("id", 0) or 0),
            }

            log.warning("AI MARKET BUY native-route trade=%s rid=%s price=%s listingItem=%s purchasedItem=%s duplicate=%s credits=%s",
                        trade_id, rid, buy_now,
                        (listing.get("itemData") or {}).get("id"), item.get("id"), bool(duplicate_ids), STATE.credits())
            response = {
                "success": True, "tradeId": trade_id, "tradeState": "closed", "bidState": "buyNow",
                "auctionInfo": [sold],
                "total": 1,
                "itemData": [native_item],
                "purchasedItems": [native_item],
                "duplicateItemIdList": duplicate_ids,
                **_credits_payload(),
            }
            return 200, {}, json_bytes(response)

        # Non-BIN offer/bid: acknowledge it as the current highest bid. We do
        # not run a competing-bid simulation yet.
        listing["currentBid"] = max(int(listing.get("startingBid", 0) or 0), amount)
        listing["bidState"] = "highest"
        listing["offers"] = 1
        return 200, {}, json_bytes({"auctionInfo": [listing], "duplicateItemIdList": [], **_credits_payload()})

    if low in ("/ut/game/fifa15/auctionhouse/status", "/ut/game/fifa15/trade/status"):
        raw_ids = str(query.get("tradeIds", query.get("tradeids", [""]))[0] or "")
        out: list[dict[str, Any]] = []
        duplicate_ids: list[dict[str, Any]] = []
        now = now_s()
        # Cheap bounded cleanup; this dictionary only contains auctions bought in
        # the current local session.
        for stale_tid, recent in list(_RECENT_AI_TRADE_STATUS.items()):
            if now - int(recent.get("created", now) or now) > _RECENT_AI_TRADE_STATUS_TTL:
                _RECENT_AI_TRADE_STATUS.pop(stale_tid, None)

        for token in raw_ids.split(","):
            try:
                tid = int(token)
            except Exception:
                continue
            recent = _RECENT_AI_TRADE_STATUS.get(tid)
            if recent is not None:
                out.append(dict(recent.get("auction") or {}))
                duplicate_ids.extend(list(recent.get("duplicateItemIdList") or []))
                continue
            decoded = _market_decode_ai_trade(tid)
            if decoded:
                out.append(_market_listing_for_resource(*decoded))
            else:
                row = STATE.user_auction(tid)
                if row:
                    out.append(_user_auction_payload(row))

        response = {
            "auctionInfo": out,
            "duplicateItemIdList": duplicate_ids,
            "total": len(out),
            **_credits_payload(),
        }
        log.warning("AI MARKET STATUS trades=%s states=%s duplicatePairs=%s credits=%s",
                    raw_ids,
                    [(x.get("tradeId"), x.get("tradeState"), x.get("bidState")) for x in out],
                    len(duplicate_ids), STATE.credits())
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    if low == "/ut/game/fifa15/auctionhouse/relist" and method in ("PUT", "POST"):
        # Relist-all uses the previous prices. Reset auction timing/AI-sale state
        # and mark each owned item forSale so the next /tradePile refresh agrees.
        now = now_s()
        relisted = []
        with STATE.lock:
            rows = STATE.conn.execute(
                "SELECT trade_id,item_id FROM auctions WHERE seller_is_user=1 AND state='expired'"
            ).fetchall()
            for row in rows:
                tid = int(row["trade_id"] if hasattr(row, "keys") else row[0])
                iid = int(row["item_id"] if hasattr(row, "keys") else row[1])
                STATE.conn.execute(
                    "UPDATE auctions SET state='active',created=?,expires=?,current_bid=0,"
                    "credited=0,sold_price=0,sold_at=0,auto_sell_after=0 WHERE trade_id=?",
                    (now, now + 3600, tid),
                )
                item_row = STATE.conn.execute("SELECT data FROM items WHERE id=?", (iid,)).fetchone()
                if item_row:
                    try:
                        item_data = json.loads(item_row[0])
                    except Exception:
                        item_data = {}
                    if isinstance(item_data, dict):
                        item_data.update({"pile": "trade", "itemState": "forSale", "untradeable": False, "tradeable": True})
                        STATE.conn.execute(
                            "UPDATE items SET pile='trade',data=? WHERE id=?",
                            (json.dumps(item_data, separators=(",", ":"), ensure_ascii=False), iid),
                        )
                relisted.append(tid)
            STATE.conn.commit()
        log.warning("TRANSFER LIST RELIST ALL trades=%s", relisted)
        return 200, {}, json_bytes({"success": True, "tradeIdList": relisted, "credits": STATE.credits()})

    if low == "/ut/game/fifa15/auctionhouse/sold" and method in ("DELETE", "POST"):
        removed = 0
        for row in STATE.list_user_auctions():
            if str(row.get("state")) == "sold" and STATE.delete_user_auction(int(row["trade_id"]), return_item=False):
                removed += 1
        return 200, {}, json_bytes({"success": True, "removed": removed, "credits": STATE.credits()})

    delete_trade = re.match(r"^/ut/(?:delete/)?game/fifa15/(?:trade|auctionhouse)/(\d+)$", low)
    if delete_trade and method in ("GET", "DELETE"):
        trade_id = int(delete_trade.group(1))
        ok = STATE.delete_user_auction(trade_id, return_item=True)
        log.warning("TRANSFER LIST REMOVE trade=%s method=%s success=%s count=%s", trade_id, method, ok, STATE.transfer_list_count())
        return 200, {"Cache-Control": "no-store"}, b""

    if low == "/ut/game/fifa15/tradepile":
        response = _transfer_pile_payload()
        log.warning("TRANSFER LIST response count=%s selling=%s sold=%s ids=%s",
                    response.get("count"), response.get("selling"), response.get("sold"),
                    [int(x.get("itemData", {}).get("id", 0) or 0) for x in response.get("auctionInfo", [])])
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    # ---- FIFA 15 PC trophy definition/image chain -------------------------
    # v0.2.6 reached these requests immediately after season/list + season/user.
    trophy_item_match = re.match(r"^/fut/items/pc/(-?\d+)\.json$", low)
    if trophy_item_match and method == "GET":
        requested_trophy = int(trophy_item_match.group(1))
        response = _season_trophy_item_response(requested_trophy)
        log.warning("SEASONS TROPHY ITEM requested=%s wire=%s", requested_trophy, response)
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    if method == "GET" and low.startswith("/fut/items/images/trophies/kc/") and low.endswith(".big"):
        payload_big = _season_trophy_big_response(path)
        log.warning("SEASONS TROPHY BIG native path=%s bytes=%s magic=%s", raw_path, len(payload_big), payload_big[:8])
        return 200, {"Content-Type": "application/octet-stream", "Cache-Control": "no-store"}, payload_big

    # ---- Single Player Seasons: FIFA 15 PC compatibility probe -----------
    if bool(CFG.get("offline_seasons_enabled", True)) and low == "/ut/game/fifa15/season":
        season_type = str(query.get("type", ["offline"])[0] or "offline").lower()
        if season_type == "offline":
            if method in ("PUT", "POST") and isinstance(payload, dict):
                # Bootstrap/probe calls can arrive without FIFA-authored opaque
                # SeasonData. Never persist active=True for those requests.
                has_season_blob = bool(str(payload.get("data", "") or ""))
                has_progress_blob = bool(str(payload.get("progressData", "") or ""))
                if has_season_blob or has_progress_blob:
                    STATE.set("offline_season_active", True)
                    STATE.update_offline_season(payload)
                    log.info("SEASONS SAVE accepted FIFA-authored SeasonData/progressData")
                else:
                    STATE.set("offline_season_active", False)
                    log.info("SEASONS SAVE ignored bootstrap/probe with no SeasonData/progressData")
            user = _offline_season_user_payload()
            return 200, {}, json_bytes(user)
        return 200, {}, json_bytes({})

    if bool(CFG.get("offline_seasons_enabled", True)) and low == "/ut/game/fifa15/season/list":
        season_type = str(query.get("type", ["offline"])[0] or "offline").lower()
        if season_type == "offline":
            all_defs = _offline_season_definitions()
            raw_divisions = str(query.get("divisionList", query.get("divisionlist", [""]))[0] or "")
            wanted: list[int] = []
            for token in re.findall(r"\d+", raw_divisions):
                try:
                    div = int(token)
                except Exception:
                    continue
                if 1 <= div <= 10 and div not in wanted:
                    wanted.append(div)
            # The working FIFA 14 PC client requires the complete ordered
            # Division 1..10 catalogue even when the request contains
            # divisionList=10. Keep the request value only as a diagnostic.
            selected = all_defs
            defs = [_season_list_wire_record(x) for x in selected]
            response = {"seasons": defs}
            log.warning("SEASONS PC-COMPAT LIST requested=%s count=%s ids=%s divisionIds=%s", wanted, len(defs), [x.get("id") for x in defs], [x.get("divisionId") for x in defs])
            return 200, {"Cache-Control": "no-store"}, json_bytes(response)
        return 200, {}, json_bytes({"seasons": []})

    if bool(CFG.get("offline_seasons_enabled", True)) and low == "/ut/game/fifa15/season/user":
        # FIFA 15 PC has two calls sharing this path family:
        #   ?type=offline                  -> current season descriptor
        #   ?divisionId=%d&seasonId=%d     -> FutSeasonLoadDataServerResponse
        if method == "GET" and ("divisionId" in query or "divisionid" in query) and ("seasonId" in query or "seasonid" in query):
            requested_div = _query_int(query, ("divisionId", "divisionid"), 10)
            requested_sid = _query_int(query, ("seasonId", "seasonid"), 1)
            response = _season_progress_wire_payload(requested_sid, requested_div)
            log.warning("SEASONS LOAD DATA query=%s wire=%s", query, response)
            return 200, {"Cache-Control": "no-store"}, json_bytes(response)

        season_type = str(query.get("type", ["offline"])[0] or "offline").lower()
        if method == "GET" and season_type == "offline":
            response = _offline_season_user_payload()
            log.warning("SEASONS CURRENT USER FIFA15-RAW active=%s userDivisionOffline=%s wireDivisionId=%s seasonId=%s round=%s data=%s progress=%s payloadActive=%s WDL=%s-%s-%s", bool(STATE.get("offline_season_active", False)), int(STATE.offline_season_state().get("division", 10) or 10), response.get("divisionId"), response.get("seasonId"), response.get("round"), bool(response.get("data")), bool(response.get("progressData")), response.get("active"), response.get("seasonGamesWon", 0), response.get("seasonGamesDraw", 0), response.get("seasonGamesLost", 0))
            return 200, {"Cache-Control": "no-store"}, json_bytes(response)
        if method in ("PUT", "POST"):
            if isinstance(payload, dict):
                # FIFA can send a bootstrap/probe POST here before it has authored
                # the opaque SeasonData/progressData required to resume a season.
                # Never turn the current season active solely because of that probe.
                has_season_blob = bool(str(payload.get("data", "") or ""))
                has_progress_blob = bool(str(payload.get("progressData", payload.get("progressdata", "")) or ""))
                if has_season_blob or has_progress_blob:
                    STATE.set("offline_season_active", True)
                    _save_season_progress_wire(payload)
                    STATE.update_offline_season(payload)
                    log.info("SEASONS USER SAVE accepted FIFA-authored SeasonData/progressData")
                else:
                    existing_data = str(STATE.get("offline_season_wire_data", "") or "")
                    existing_progress = str(STATE.get("offline_season_wire_progress_data", "") or "")
                    STATE.set("offline_season_active", bool(existing_data or existing_progress))
                    log.info("SEASONS USER SAVE ignored bootstrap/probe with no SeasonData/progressData")
            return 200, {}, json_bytes(_offline_season_user_payload())

    # Native SeasonUpdate/SeasonLoadData family. The URL template in CardsDLL
    # is one level deeper than season/<id>/user: the client composes
    # season/<seasonId>/division/<divisionNumber>/user. Preserve its own blob.
    season_progress = re.match(r"^/ut/game/fifa15/season/(\d+)/division/(\d+)/user$", low)
    if bool(CFG.get("offline_seasons_enabled", True)) and season_progress:
        season_id = int(season_progress.group(1))
        division_number = int(season_progress.group(2))
        if method in ("PUT", "POST"):
            STATE.set("offline_season_division", max(1, min(10, int(division_number))))
            if isinstance(payload, dict):
                # This endpoint is FIFA saving its opaque SeasonData blob. The
                # wire `round` is *not* proof that a match has been completed:
                # FIFA writes round=1 while merely opening/starting Division 10.
                # Preserve the client blob verbatim and advance semantic round/
                # W-D-L only from /match/end.
                has_season_blob = bool(str(payload.get("data", "") or ""))
                has_progress_blob = bool(str(payload.get("progressData", payload.get("progressdata", "")) or ""))
                if has_season_blob or has_progress_blob:
                    STATE.set("offline_season_active", True)
                    _save_season_progress_wire(payload)
                else:
                    existing_data = str(STATE.get("offline_season_wire_data", "") or "")
                    existing_progress = str(STATE.get("offline_season_wire_progress_data", "") or "")
                    STATE.set("offline_season_active", bool(existing_data or existing_progress))
                    log.info("SEASONS DIVISION SAVE ignored bootstrap/probe with no SeasonData/progressData")
            response = _season_progress_wire_payload(season_id, division_number)
            log.warning("SEASONS SAVE season=%s division=%s body=%s response=%s", season_id, division_number, payload, response)
            return 200, {"Cache-Control": "no-store"}, json_bytes(response)
        if method == "GET":
            response = _season_progress_wire_payload(season_id, division_number)
            log.warning("SEASONS LOAD season=%s division=%s response=%s", season_id, division_number, response)
            return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    if bool(CFG.get("offline_seasons_enabled", True)) and low == "/ut/game/fifa15/season/user/history":
        # FIFA's Season History tile is populated from this response, not from
        # the normal FUT /user header record. Earlier builds always returned {},
        # which is why the mode showed 0-0-0 even while the header had settled
        # results. Publish the persistent local FUT W/D/L plus the season-history
        # counters the FIFA 15 CardsDLL knows about.
        wins = int(STATE.get("record_wins", 0) or 0)
        draws = int(STATE.get("record_draws", 0) or 0)
        losses = int(STATE.get("record_losses", 0) or 0)
        response = {
            "seasonGamesWon": wins,
            "seasonGamesDraw": draws,
            "seasonGamesLost": losses,
            "seasonWins": wins,
            "seasonOnlineWins": 0,
            "seasonOnlineDraws": 0,
            "seasonOnlineLosses": 0,
            "seasonCompleted": int(STATE.get("offline_seasons_completed", 0) or 0),
            "seasonTitlesWon": int(STATE.get("offline_season_trophies", 0) or 0),
            "seasonPromotions": int(STATE.get("offline_season_promotions", 0) or 0),
            "seasonRelegations": int(STATE.get("offline_season_relegations", 0) or 0),
            "seasonCoins": int(STATE.get("offline_season_coins", 0) or 0),
            "seasonsScoredGoals": int(STATE.get("offline_season_history_goals_for", 0) or 0),
            "seasonConcededGoals": int(STATE.get("offline_season_history_goals_against", 0) or 0),
        }
        log.warning("SEASONS HISTORY wire=%s", response)
        return 200, {"Cache-Control": "no-store"}, json_bytes(response)

    season_reset = re.match(r"^/ut/game/fifa15/season/(offline|online)/reset$", low)
    if bool(CFG.get("offline_seasons_enabled", True)) and season_reset:
        if season_reset.group(1) == "offline":
            division = _query_int(query, ("divisionId", "divisionid"), STATE.offline_season_state()["division"])
            st = STATE.reset_offline_season(division)
            return 200, {}, json_bytes({"success": True, "state": st})
        return 200, {}, json_bytes({"success": True})

    season_quit = re.match(r"^/ut/game/fifa15/season/(\d+)/division/(\d+)$", low)
    if bool(CFG.get("offline_seasons_enabled", True)) and season_quit and method in ("DELETE", "PUT", "POST"):
        # FIFA can touch this route while unwinding a forfeited *match*. Resetting
        # the whole season here made a normal DNF/forfeit send the player back to
        # Game 1. The explicit /season/offline/reset route remains the only local
        # full-season reset path.
        division = int(season_quit.group(2))
        st = STATE.offline_season_state()
        log.warning("SEASONS DIVISION TERMINAL ACK preserved season=%s division=%s method=%s state=%s body=%s", season_quit.group(1), division, method, st, payload if isinstance(payload, dict) else {})
        return 200, {"Cache-Control": "no-store"}, json_bytes({"success": True, "state": st})

    # ---- Native FIFA consumable application -----------------------------
    # CardsDLL can address a consumable either by definition resourceId or by
    # the specific owned item instance. The body carries apply/applyTo targets.
    apply_resource = re.match(r"^/ut/game/fifa15/item/resource/(\d+)$", low)
    apply_item = re.match(r"^/ut/game/fifa15/item/(\d+)$", low)
    if method in ("PUT", "POST") and (
        apply_resource is not None
        or (apply_item is not None and isinstance(payload, dict) and ("apply" in payload or "applyTo" in payload))
    ):
        try:
            doc = payload if isinstance(payload, dict) else {}
            rows = doc.get("apply", doc.get("applyTo", []))
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                rows = [rows]
            targets: list[int] = []
            for row in rows:
                raw = row.get("id", row.get("itemId", 0)) if isinstance(row, dict) else row
                try:
                    iid = int(raw or 0)
                except Exception:
                    iid = 0
                if iid > 0 and iid not in targets:
                    targets.append(iid)
            if not targets:
                raise ValueError("missing consumable apply target")
            if apply_resource is not None:
                resource_id = int(apply_resource.group(1))
                addressed_item = None
            else:
                addressed_item = int(apply_item.group(1))
                owned = STATE.get_item(addressed_item)
                if not owned or str(owned.get("itemType", "player")) == "player":
                    raise ValueError("addressed item is not an owned consumable")
                resource_id = int(owned.get("resourceId", 0) or 0)
            result = STATE.apply_consumable(resource_id, targets)
            log.warning(
                "CONSUMABLE APPLY HTTP resource=%s addressedItem=%s targets=%s effect=%s",
                resource_id, addressed_item, targets, result.get("effect"),
            )
            # FIFA 15 does not always refetch the target ItemData after a
            # successful apply.  Returning the canonical mutated player lets the
            # squad screen update contracts/fitness/training immediately while
            # remaining compatible with clients that only care about HTTP 200.
            changed_native = [
                _native_player_item(x) if str(x.get("itemType", "player")) == "player" else x
                for x in (result.get("itemData", []) if isinstance(result.get("itemData", []), list) else [])
                if isinstance(x, dict)
            ]
            response = {
                "success": True,
                "consumedItemId": int(result.get("consumedItemId", 0) or 0),
                "itemData": changed_native,
                "items": changed_native,
            }
            if changed_native:
                response["item"] = changed_native[0]
            return 200, {"Cache-Control": "no-store"}, json_bytes(response)
        except Exception as exc:
            log.warning("CONSUMABLE APPLY ERROR path=%s body=%s error=%s", low, payload, exc)
            return 400, {"Cache-Control": "no-store"}, json_bytes({"code": "400", "reason": str(exc)})

    # ---- Native FIFA discard / quick-sell routes -------------------------
    # Single item:
    #   DELETE /ut/game/fifa15/item/<itemId>
    # Multiple items ("Quick Sell All"):
    #   POST /ut/delete/game/fifa15/item
    #
    # FIFA expects totalCredits + items[] in the response.
    single_discard = re.match(r"^/ut/game/fifa15/item/(\d+)$", low)
    if single_discard and method == "DELETE":
        iid = int(single_discard.group(1))
        total_credits, deleted_ids = STATE.discard_items([iid])
        return 200, {}, json_bytes({
            "totalCredits": total_credits,
            "credits": total_credits,
            "items": [{"id": x} for x in deleted_ids],
            "currencies": [{
                "name": "coins",
                "funds": total_credits,
                "finalFunds": total_credits,
            }],
        })

    if low == "/ut/delete/game/fifa15/item" and method == "POST":
        ids = []
        if isinstance(payload, dict):
            raw_ids = payload.get("itemId", [])
            if not isinstance(raw_ids, list):
                raw_ids = [raw_ids]
            ids.extend(raw_ids)

            # Be tolerant if this particular PC build sends itemData instead.
            raw_data = payload.get("itemData", [])
            if isinstance(raw_data, dict):
                raw_data = [raw_data]
            if isinstance(raw_data, list):
                for x in raw_data:
                    if isinstance(x, dict):
                        ids.append(x.get("id") or x.get("itemId"))

        total_credits, deleted_ids = STATE.discard_items(ids)
        return 200, {}, json_bytes({
            "totalCredits": total_credits,
            "credits": total_credits,
            "items": [{"id": x} for x in deleted_ids],
            "currencies": [{
                "name": "coins",
                "funds": total_credits,
                "finalFunds": total_credits,
            }],
        })

    if low == "/ut/game/fifa15/item" and method in ("PUT", "POST"):
        results = []
        duplicate_results = []
        data_list = payload.get("itemData", []) if isinstance(payload, dict) else []
        if isinstance(data_list, dict):
            data_list = [data_list]
        batch_mode = len(data_list) > 1

        for change in data_list:
            try:
                iid = int(change.get("id") or change.get("itemId"))
            except Exception:
                continue
            requested_pile = change.get("pile")
            current_item = STATE.get_item(iid) or {}
            pile = str(requested_pile if requested_pile is not None else current_item.get("pile", "club"))

            if requested_pile is not None and pile in ("club", "squad") and STATE.would_duplicate_owned_player(iid):
                # Keep the duplicate physically in Unassigned in every case.
                STATE.mark_item_duplicate(iid, True)
                duplicate_results.append({"itemId": iid})

                if batch_mode:
                    # Store All: explicitly acknowledge the item while telling FIFA
                    # that its resulting pile is still Unassigned.  v5 omitted the
                    # duplicate from itemData entirely; the database was correct but
                    # the native client optimistically animated every submitted card
                    # into the club.  Pairing this result with duplicateItemIdList
                    # gives the client both pieces of state without using success=False
                    # (which made FIFA 15 treat the whole batch as fatal in v3).
                    results.append({
                        "id": iid,
                        "pile": "unassigned",
                        "success": True,
                    })
                    log.info("Store All kept duplicate item %d visibly unassigned", iid)
                    continue

                # Native FIFA 15 PC handles duplicate state in NewItemsScreen itself.
                # Returning a failed /item move causes this build to tear down FUT auth,
                # so acknowledge the request while preserving the card in Unassigned.
                results.append({
                    "id": iid,
                    "pile": "unassigned",
                    "success": True,
                    "IS_DUPLICATE": True,
                })
                log.info("Kept duplicate item %d in unassigned using native UI marker", iid)
                continue

            # The Transfer List is a persistent item pile first; listing it on
            # /auctionhouse is a separate action. Enforce capacity and never allow
            # a listed auction to be silently yanked back to club by a stale UI PUT.
            current_pile = str(current_item.get("pile", "club") or "club")
            if requested_pile is not None and pile == "trade" and current_pile not in ("trade", "tradepile") and STATE.transfer_list_count() >= 100:
                log.warning("TRANSFER LIST full: rejected item=%s currentPile=%s", iid, current_pile)
                results.append({"id": iid, "pile": current_pile, "success": False, "reason": "TRADE_PILE_FULL"})
                continue
            if requested_pile is not None and pile in ("club", "squad"):
                existing_auction = STATE.user_auction_for_item(iid)
                if existing_auction and str(existing_auction.get("state", "")) == "active":
                    log.warning("TRANSFER LIST active auction blocks pile move item=%s trade=%s", iid, existing_auction.get("trade_id"))
                    results.append({"id": iid, "pile": current_pile, "success": False, "reason": "ITEM_LISTED"})
                    continue

            merged_item = STATE.update_item_fields(iid, change)
            ok = merged_item is not None
            if requested_pile is not None:
                ok = STATE.update_item_pile(iid, pile) and ok
            log.info("ITEM UPDATE id=%s pile=%s explicitPile=%s fields=%s success=%s transferCount=%s",
                     iid, pile, requested_pile is not None, sorted(change.keys()), ok, STATE.transfer_list_count())
            results.append({"id": iid, "pile": pile, "success": ok})

        response = {"itemData": results}
        if duplicate_results:
            response["duplicateItemIdList"] = duplicate_results
        return 200, {}, json_bytes(response)

    suffix = low
    m = re.match(r"^/ut/(?:game/)?[^/]+/(.*)$", low)
    if m:
        suffix = "/" + m.group(1)

    if suffix in ("/usermassinfo", "/user/massinfo"):
        return 200, {}, json_bytes(user_mass_info())
    if suffix.startswith("/defid"):
        rid = 0
        try:
            rid = int(query.get("defId", [0])[0])
        except Exception:
            pass
        variants = []
        if rid:
            for vrid, vmeta in PLAYER_DB.items():
                try:
                    asset = int(vmeta.get("assetId", vrid) or vrid)
                except Exception:
                    continue
                if asset != rid and int(vrid) != rid:
                    continue
                variants.append({
                    "id": 0, "assetId": asset, "resourceId": int(vrid), "itemType": "player",
                    "rareflag": int(vmeta.get("rareflag", 1)), "rating": int(vmeta.get("rating", 0)),
                    "discardValue": STATE.player_discard_value(int(vrid)), "preferredPosition": str(vmeta.get("preferredPosition", "")),
                    "leagueId": int(vmeta.get("leagueId", 0)), "teamid": int(vmeta.get("teamid", 0)),
                    "nation": int(vmeta.get("nation", 0)), "attributeList": player_attribute_list(int(vrid)),
                })
            variants.sort(key=lambda x: int(x.get("rating", 0)), reverse=True)
        return 200, {}, json_bytes({"itemData": variants})

    if CFG.get("debug_unknown_http", True):
        log.warning("Unknown FUT/POW request: %s %s body=%s", method, raw_path, body[:500])
    return 200, {"X-LocalFUT15-Unknown": "1"}, json_bytes({})


class FutHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LocalFUT15/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("FUT8199 %s - %s", self.client_address[0], fmt % args)

    def _go(self) -> None:
        n = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(n) if n else b""
        hdrs = {k: v for k, v in self.headers.items()}
        try:
            status, extra, out = route_fut(self.command, self.path, hdrs, body)
        except Exception:
            log.exception("FUT handler error")
            status, extra, out = 500, {}, json_bytes({"error": "local server exception"})
        self.send_response(status)
        content_type = extra.pop("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Connection", "keep-alive")
        if self.path.startswith("/ut") or self.path.startswith("//ut"):
            self.send_header("X-UT-SID", _ut_sid())
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(out)

    do_GET = _go
    do_POST = _go
    do_PUT = _go
    do_DELETE = _go
    do_OPTIONS = _go


class RedirectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LocalFUT15Redirector/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("REDIR42230 %s - %s", self.client_address[0], fmt % args)

    def _reply(self) -> None:
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n) if n else b""
        seq = self.headers.get("X-BLAZE-SEQNO", "0")
        log.info("Redirector request %s %s body=%s", self.command, self.path, raw[:800])
        ip_int = 2130706433  # 127.0.0.1 in host-order integer form used by old redirector XML.
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<serverinstanceinfo>
    <address member="0">
        <valu>
            <hostname>127.0.0.1</hostname>
            <ip>{ip_int}</ip>
            <port>{int(CFG["blaze_port"])}</port>
        </valu>
    </address>
    <secure>0</secure>
</serverinstanceinfo>'''.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(xml)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(xml)

    do_POST = _reply
    do_GET = _reply


class QosHandler(BaseHTTPRequestHandler):
    """FIFA 15 QoS HTTP service learned from the successful V3 capture."""
    protocol_version = "HTTP/1.1"
    server_version = "LocalFUT15QoS/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("QOS17502 %s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        path = parsed.path.lower()
        qos_ip_le = 16777343  # 127.0.0.1 interpreted as little-endian uint32.

        if path == "/qos/qos":
            qtyp = q.get("qtyp", ["1"])[0]
            if qtyp == "2":
                xml = (
                    f'<?xml version="1.0" encoding="utf-8"?><qos>'
                    f'<numprobes>10</numprobes><qosport>{int(CFG["qos_port"])}</qosport>'
                    f'<probesize>1200</probesize><qosip>{qos_ip_le}</qosip>'
                    f'<requestid>1234</requestid><reqsecret>5678</reqsecret></qos>'
                ).encode("utf-8")
            else:
                xml = (
                    f'<?xml version="1.0" encoding="utf-8"?><qos>'
                    f'<numprobes>0</numprobes><qosport>{int(CFG["qos_port"])}</qosport>'
                    f'<probesize>0</probesize><qosip>{qos_ip_le}</qosip>'
                    f'<requestid>1</requestid><reqsecret>0</reqsecret></qos>'
                ).encode("utf-8")
            status = 200
        elif path == "/qos/firewall":
            xml = (
                f'<?xml version="1.0" encoding="utf-8"?><firewall>'
                f'<ips><ips>{qos_ip_le}</ips><ips>{qos_ip_le}</ips></ips>'
                f'<numinterfaces>2</numinterfaces>'
                f'<ports><ports>{int(CFG["qos_port"])}</ports><ports>{int(CFG["qos_port"])}</ports></ports>'
                f'<requestid>1234</requestid><reqsecret>5678</reqsecret></firewall>'
            ).encode("utf-8")
            status = 200
        elif path == "/qos/firetype":
            xml = b'<?xml version="1.0" encoding="utf-8"?><firetype><firetype>2</firetype></firetype>'
            status = 200
        else:
            xml = b"not found"
            status = 404

        self.send_response(status)
        self.send_header("Content-Type", "application/xml; charset=utf-8" if status == 200 else "text/plain")
        self.send_header("Content-Length", str(len(xml)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(xml)


class EaswHandler(BaseHTTPRequestHandler):
    """Legacy EASW service used between Blaze login and FUT /ut/auth."""
    protocol_version = "HTTP/1.1"
    server_version = "LocalFUT15EASW/0.1"

    ROSTER_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<squad>
  <squadInfoSet>
    <squadInfo platform="pc64">
      <dbSchemaCRC>596426fe3525c25b90593b800b9ce5c3c61ccab5</dbSchemaCRC>
      <dbMajor>1</dbMajor><dbMinor>0</dbMinor>
      <dbMajorCRC>0</dbMajorCRC><dbMinorCRC>0</dbMinorCRC>
      <dbMajorLoc></dbMajorLoc><dbMinorLoc></dbMinorLoc>
      <dbFUTVer>1</dbFUTVer><dbFUTCRC>0</dbFUTCRC><dbFUTLoc></dbFUTLoc>
    </squadInfo>
    <squadInfo platform="pc64">
      <dbSchemaCRC>00e20ae6ad44d892ad15ea7f060ce6d97ca9e730</dbSchemaCRC>
      <dbMajor>1</dbMajor><dbMinor>0</dbMinor>
      <dbMajorCRC>0</dbMajorCRC><dbMinorCRC>0</dbMinorCRC>
      <dbMajorLoc></dbMajorLoc><dbMinorLoc></dbMinorLoc>
      <dbFUTVer>1</dbFUTVer><dbFUTCRC>0</dbFUTCRC><dbFUTLoc></dbFUTLoc>
    </squadInfo>
  </squadInfoSet>
</squad>'''

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("EASW42232 %s - %s", self.client_address[0], fmt % args)

    def _send(self, status: int, body: bytes, content_type: str = "text/xml", extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n:
            self.rfile.read(n)
        if urllib.parse.urlsplit(self.path).path.lower() == "/extension":
            self._send(
                200,
                b'<?xml version="1.0" encoding="UTF-8"?>\n<result/>\n',
                "text/xml",
                {
                    "EASW-Session": "fut15-local-easw-session",
                    "EASW-Token": "fut15-local-easw-token",
                },
            )
        else:
            self._send(200, b'<?xml version="1.0" encoding="UTF-8"?>\n<result/>\n')

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path.lower()
        if path == "/roster":
            self._send(200, self.ROSTER_XML)
        elif path in ("/ctl", "/routing"):
            self._send(404, b"not found", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")


# ---- Blaze Fire2 / TDF ----------------------------------------------------
# FIFA 15's 10051 connection uses the Fire2 Blaze frame used by later
# BlazeSDK builds. The captured client packet is Util.PreAuth (component 9,
# command 7). 0.1.2 only recorded it; 0.1.3 parses/replies and keeps the
# session alive so later requests can be learned/handled locally.

_TDF_VARINT = 0x0
_TDF_STRING = 0x1
_TDF_BLOB = 0x2
_TDF_GROUP = 0x3
_TDF_LIST = 0x4
_TDF_MAP = 0x5
_TDF_UNION = 0x6
_TDF_OBJECT_TYPE = 0x8
_TDF_OBJECT_ID = 0x9


def _tdf_tag(tag: str | bytes, value_type: int) -> bytes:
    """Encode a 1-4 character Blaze TDF tag plus type byte."""
    raw = tag.encode("ascii") if isinstance(tag, str) else bytes(tag)
    if not 1 <= len(raw) <= 4:
        raise ValueError(f"TDF tag must be 1-4 bytes: {raw!r}")
    out = [0, 0, 0, int(value_type) & 0xFF]
    if len(raw) > 0:
        out[0] |= (raw[0] & 0x40) << 1
        out[0] |= (raw[0] & 0x10) << 2
        out[0] |= (raw[0] & 0x0F) << 2
    if len(raw) > 1:
        out[0] |= (raw[1] & 0x40) >> 5
        out[0] |= (raw[1] & 0x10) >> 4
        out[1] |= (raw[1] & 0x0F) << 4
    if len(raw) > 2:
        out[1] |= (raw[2] & 0x40) >> 3
        out[1] |= (raw[2] & 0x10) >> 2
        out[1] |= (raw[2] & 0x0C) >> 2
        out[2] |= (raw[2] & 0x03) << 6
    if len(raw) > 3:
        out[2] |= (raw[3] & 0x40) >> 1
        out[2] |= raw[3] & 0x1F
    return bytes(out)


def _tdf_varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        # Blaze serializes signed integers through their unsigned bit pattern.
        value &= (1 << 64) - 1
    if value < 0x40:
        return bytes([value])
    out = bytearray([(value & 0x3F) | 0x80])
    value >>= 6
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def _tdf_str_value(value: str) -> bytes:
    raw = str(value).encode("utf-8")
    return _tdf_varint(len(raw) + 1) + raw + b"\x00"


def _tdf_field_int(tag: str, value: int) -> bytes:
    return _tdf_tag(tag, _TDF_VARINT) + _tdf_varint(value)


def _tdf_field_str(tag: str, value: str) -> bytes:
    return _tdf_tag(tag, _TDF_STRING) + _tdf_str_value(value)


def _tdf_field_blob(tag: str, value: bytes) -> bytes:
    raw = bytes(value)
    return _tdf_tag(tag, _TDF_BLOB) + _tdf_varint(len(raw)) + raw


def _tdf_field_object_id(tag: str, component: int, entity_type: int, entity_id: int) -> bytes:
    """Encode Blaze Heat2 ObjectId: component, entity type, then 64-bit id as varints."""
    return (
        _tdf_tag(tag, _TDF_OBJECT_ID)
        + _tdf_varint(component)
        + _tdf_varint(entity_type)
        + _tdf_varint(entity_id)
    )


def _tdf_field_group(tag: str, body: bytes) -> bytes:
    return _tdf_tag(tag, _TDF_GROUP) + body + b"\x00"


def _tdf_field_list_int(tag: str, values: list[int] | tuple[int, ...]) -> bytes:
    out = bytearray(_tdf_tag(tag, _TDF_LIST))
    out.append(_TDF_VARINT)
    out.extend(_tdf_varint(len(values)))
    for value in values:
        out.extend(_tdf_varint(value))
    return bytes(out)


def _tdf_field_list_groups(tag: str, groups: list[bytes]) -> bytes:
    out = bytearray(_tdf_tag(tag, _TDF_LIST))
    out.append(_TDF_GROUP)
    out.extend(_tdf_varint(len(groups)))
    for body in groups:
        out.extend(body)
        out.append(0)  # each group body terminator
    return bytes(out)


def _tdf_field_map_str_str(tag: str, values: list[tuple[str, str]]) -> bytes:
    out = bytearray(_tdf_tag(tag, _TDF_MAP))
    out.extend((_TDF_STRING, _TDF_STRING))
    out.extend(_tdf_varint(len(values)))
    for key, value in values:
        out.extend(_tdf_str_value(key))
        out.extend(_tdf_str_value(value))
    return bytes(out)


def _tdf_field_map_str_group(tag: str, values: list[tuple[str, bytes]]) -> bytes:
    out = bytearray(_tdf_tag(tag, _TDF_MAP))
    out.extend((_TDF_STRING, _TDF_GROUP))
    out.extend(_tdf_varint(len(values)))
    for key, body in values:
        out.extend(_tdf_str_value(key))
        out.extend(body)
        out.append(0)  # group terminator
    return bytes(out)


def _tdf_decode_varint(raw: bytes, pos: int = 0) -> tuple[int, int]:
    if pos >= len(raw):
        raise ValueError("truncated TDF varint")
    first = raw[pos]
    pos += 1
    value = first & 0x3F
    shift = 6
    if first & 0x80:
        while True:
            if pos >= len(raw):
                raise ValueError("truncated TDF varint")
            b = raw[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
    return value, pos


def _tdf_get_string(raw: bytes, tag: str) -> str | None:
    marker = _tdf_tag(tag, _TDF_STRING)
    p = raw.find(marker)
    if p < 0:
        return None
    p += 4
    try:
        n, p = _tdf_decode_varint(raw, p)
    except ValueError:
        return None
    if n <= 0 or p + n > len(raw):
        return None
    value = raw[p:p+n]
    if value.endswith(b"\x00"):
        value = value[:-1]
    return value.decode("utf-8", errors="replace")




def _tdf_get_int_last(raw: bytes, tag: str) -> int | None:
    """Return the last matching Blaze varint field for nested report payloads."""
    marker = _tdf_tag(tag, _TDF_VARINT)
    p = raw.rfind(marker)
    if p < 0:
        return None
    p += len(marker)
    try:
        value, _ = _tdf_decode_varint(raw, p)
        return int(value)
    except ValueError:
        return None


def _game_reporting_result_notification_payload(reporting_id: int) -> bytes:
    """Blaze GameReporting::ResultNotification terminal-success body."""
    rid = max(0, int(reporting_id))
    return (
        _tdf_field_int("EROR", 0)
        + _tdf_field_int("FNL", 1)
        + _tdf_field_int("GHID", rid)
        + _tdf_field_int("GRID", rid)
    )


def _tdf_debug_summary(raw: bytes) -> str:
    """Best-effort non-mutating TDF scout used only for compatibility logging."""
    if not raw:
        return "<empty>"
    # Extract printable ASCII runs; method/adaptor names often survive here.
    strings = []
    cur = bytearray()
    for b in raw:
        if 32 <= b <= 126:
            cur.append(b)
        else:
            if len(cur) >= 3:
                strings.append(cur.decode("ascii", errors="replace"))
            cur.clear()
    if len(cur) >= 3:
        strings.append(cur.decode("ascii", errors="replace"))

    # Best-effort scan for packed Blaze TDF 3-char tags. Do not attempt to parse
    # values recursively; malformed guesses are harmless because this is logging only.
    tags = []
    for i in range(max(0, len(raw) - 3)):
        chunk = raw[i:i+3]
        # Packed TDF tags commonly decode to uppercase alnum/_ names. Keep only
        # plausible candidates to avoid a wall of noise.
        try:
            v = int.from_bytes(chunk, "big")
            chars = [
                ((v >> 18) & 0x3F) + 32,
                ((v >> 12) & 0x3F) + 32,
                ((v >> 6) & 0x3F) + 32,
                (v & 0x3F) + 32,
            ]
            name = ''.join(chr(c) for c in chars).rstrip()
            if 2 <= len(name) <= 4 and all(c.isupper() or c.isdigit() or c == '_' for c in name):
                if name not in tags:
                    tags.append(name)
        except Exception:
            pass
        if len(tags) >= 24:
            break
    return f"hex={raw[:256].hex()} ascii={strings[:20]} tags={tags}"

def _blaze_preauth_payload() -> bytes:
    """FIFA 15 PC PreAuth payload reconstructed from the successful FIFA 15 PC trace.

    The important part is QOSS: FIFA uses the Blaze reply to discover the QoS
    HTTP service. 0.1.8 conflated that service with Blaze itself; the original
    topology uses Blaze on 10051 and QoS on 17502.
    """
    core_conf = _tdf_field_map_str_str(
        "CONF",
        [
            ("connIdleTimeout", "120s"),
            ("defaultRequestTimeout", "80s"),
            ("pingPeriod", "20s"),
            ("voipHeadsetUpdateRate", "1000"),
            ("xlspConnectionIdleTimeout", "300"),
        ],
    )

    bwps = bytearray()
    bwps += _tdf_field_str("PSA", "127.0.0.1")
    bwps += _tdf_field_int("PSP", int(CFG["qos_port"]))
    bwps += _tdf_field_str("SNA", "qos")

    latency = bytearray()
    latency += _tdf_field_str("PSA", "127.0.0.1")
    latency += _tdf_field_int("PSP", int(CFG["qos_port"]))
    latency += _tdf_field_str("SNA", "ea-sjc")

    qoss = bytearray()
    qoss += _tdf_field_group("BWPS", bytes(bwps))
    qoss += _tdf_field_int("LNP", 10)
    qoss += _tdf_field_map_str_group("LTPS", [("ea-sjc", bytes(latency))])
    qoss += _tdf_field_int("SVID", 1161889797)
    qoss += _tdf_field_int("TIME", 5000)

    body = bytearray()
    body += _tdf_field_str("ASRC", "303107")
    body += _tdf_field_list_int("CIDS", [1, 9, 35, 30722])
    body += _tdf_field_group("CONF", core_conf)
    body += _tdf_field_int("EEFA", 1)
    body += _tdf_field_str("ESRC", "303107")
    body += _tdf_field_str("INST", "fifa-2015-pc")
    body += _tdf_field_int("MAID", 89)
    body += _tdf_field_int("MINR", 0)
    body += _tdf_field_str("NASP", "cem_ea_id")
    body += _tdf_field_str("PILD", "")
    body += _tdf_field_str("PLAT", "pc")
    body += _tdf_field_group("QOSS", bytes(qoss))
    body += _tdf_field_str("RSRC", "303107")
    body += _tdf_field_str("SVER", "Blaze 14.2.1.1.0")
    return bytes(body)


def _blaze_auth_payload() -> bytes:
    persona = int(CFG["persona_id"])
    nucleus = int(CFG["nucleus_id"])
    session = bytearray()
    session += _tdf_field_int("1CON", 0)
    session += _tdf_field_int("BUID", persona)
    session += _tdf_field_int("FRST", 0)
    session += _tdf_field_str("KEY", STATE.token())
    session += _tdf_field_int("LLOG", now_s())
    session += _tdf_field_str("MAIL", "local@localhost")
    pdtl = bytearray()
    pdtl += _tdf_field_str("DSNM", str(_persona_name()))
    pdtl += _tdf_field_int("LAST", 0)
    pdtl += _tdf_field_int("PID", persona)
    pdtl += _tdf_field_int("PLAT", 4)
    pdtl += _tdf_field_int("STAS", 0)
    pdtl += _tdf_field_int("XREF", nucleus)
    session += _tdf_field_group("PDTL", bytes(pdtl))
    session += _tdf_field_int("UID", nucleus)

    body = bytearray()
    body += _tdf_field_int("CNTX", 0)
    body += _tdf_field_int("ERRC", 0)
    body += _tdf_field_str("SKEY", STATE.token())
    body += _tdf_field_int("ANON", 0)
    body += _tdf_field_int("NTOS", 0)
    body += _tdf_field_group("SESS", bytes(session))
    body += _tdf_field_int("SPAM", 0)
    body += _tdf_field_int("UNDR", 0)
    return bytes(body)


def _blaze_entitlements_payload() -> bytes:
    ent = bytearray()
    ent += _tdf_field_str("DEVI", "")
    ent += _tdf_field_str("GDAY", "2014-09-25T00:00Z")
    ent += _tdf_field_str("GNAM", "FIFA15PC")
    ent += _tdf_field_int("ID", 1024871)
    ent += _tdf_field_int("ISCO", 0)
    ent += _tdf_field_int("PID", 0)
    ent += _tdf_field_str("PJID", "1024871")
    ent += _tdf_field_int("PRCA", 2)
    ent += _tdf_field_str("PRID", "FIFA15_PC_ONLINE_ACCESS")
    ent += _tdf_field_int("STAT", 1)
    ent += _tdf_field_int("STRC", 0)
    ent += _tdf_field_str("TAG", "ONLINE_ACCESS")
    ent += _tdf_field_str("TDAY", "")
    ent += _tdf_field_int("TYPE", 1)
    ent += _tdf_field_int("UCNT", 0)
    ent += _tdf_field_int("VER", 0)
    return _tdf_field_list_groups("NLST", [bytes(ent)])


def _blaze_postauth_payload() -> bytes:
    telemetry = bytearray()
    telemetry += _tdf_field_str("ADRS", "127.0.0.1")
    telemetry += _tdf_field_int("ANON", 0)
    telemetry += _tdf_field_str("DISA", "")
    telemetry += _tdf_field_str("FILT", "-UION/****")
    telemetry += _tdf_field_int("PORT", 0)
    telemetry += _tdf_field_int("SDLY", 15000)
    telemetry += _tdf_field_str("SESS", "LOCALFUT15")
    telemetry += _tdf_field_str("SKEY", "")
    telemetry += _tdf_field_int("SPCT", 0)

    ticker = bytearray()
    ticker += _tdf_field_str("ADRS", "127.0.0.1")
    ticker += _tdf_field_int("PORT", 0)
    ticker += _tdf_field_str("SKEY", "")

    urop = bytearray()
    urop += _tdf_field_int("TMOP", 1)
    urop += _tdf_field_int("UID", int(CFG["persona_id"]))

    body = bytearray()
    body += _tdf_field_group("TELE", bytes(telemetry))
    body += _tdf_field_group("TICK", bytes(ticker))
    body += _tdf_field_group("UROP", bytes(urop))
    return bytes(body)


def _blaze_ping_payload() -> bytes:
    # Different Blaze generations use STIM or TIME. Supplying both is harmless
    # for tag-addressed TDF readers and maximizes compatibility with FIFA 15.
    t = now_s()
    return _tdf_field_int("STIM", t) + _tdf_field_int("TIME", t)


def _blaze_empty_config_payload() -> bytes:
    return _tdf_field_map_str_str("CONF", [])


@dataclass
class Fire2Packet:
    payload_size: int
    metadata_size: int
    component: int
    command: int
    msg_num: int
    msg_type: int
    metadata: bytes
    payload: bytes
    raw: bytes


def _fire2_try_parse(buf: bytearray) -> Fire2Packet | None:
    if len(buf) < 16:
        return None
    payload_size = int.from_bytes(buf[0:4], "big")
    metadata_size = int.from_bytes(buf[4:6], "big")
    total = 16 + metadata_size + payload_size
    if payload_size > 16 * 1024 * 1024 or metadata_size > 1024 * 1024:
        raise ValueError(f"unreasonable Fire2 sizes payload={payload_size} metadata={metadata_size}")
    if len(buf) < total:
        return None
    raw = bytes(buf[:total])
    del buf[:total]
    component = int.from_bytes(raw[6:8], "big")
    command = int.from_bytes(raw[8:10], "big")
    msg_num = int.from_bytes(raw[10:13], "big")
    msg_type = raw[13] >> 5
    metadata = raw[16:16 + metadata_size]
    payload = raw[16 + metadata_size:]
    return Fire2Packet(payload_size, metadata_size, component, command, msg_num, msg_type, metadata, payload, raw)


def _fire2_build(component: int, command: int, msg_num: int, msg_type: int, payload: bytes = b"", metadata: bytes = b"") -> bytes:
    out = bytearray()
    out += len(payload).to_bytes(4, "big")
    out += len(metadata).to_bytes(2, "big")
    out += int(component).to_bytes(2, "big")
    out += int(command).to_bytes(2, "big")
    out += (int(msg_num) & 0xFFFFFF).to_bytes(3, "big")
    out += bytes([(int(msg_type) & 0x07) << 5, 0, 0])
    out += metadata
    out += payload
    return bytes(out)


def _save_fire2(packet: Fire2Packet, peer: tuple[str, int], kind: str = "rx") -> Path:
    stamp = f"{int(time.time()*1000)}-{peer[0].replace(':','_')}-{peer[1]}"
    path = LOGS / f"fire2-{kind}-c{packet.component}-k{packet.command}-m{packet.msg_num}-{stamp}.bin"
    path.write_bytes(packet.raw)
    path.with_suffix(".hex.txt").write_text(packet.raw.hex(" "), encoding="utf-8")
    return path


def _blaze_fifa35_auth_bootstrap_payload() -> bytes:
    """Exact FIFA 15 c35/k10 login-response shape learned from the V3 trace."""
    persona = int(CFG["persona_id"])

    pdtl = bytearray()
    pdtl += _tdf_field_str("DSNM", str(_persona_name()))
    pdtl += _tdf_field_int("PID", persona)
    pdtl += _tdf_field_int("PLAT", 4)

    sess = bytearray()
    sess += _tdf_field_int("1CON", 0)
    sess += _tdf_field_int("BUID", persona)
    sess += _tdf_field_int("FRST", 0)
    sess += _tdf_field_str("KEY", "localfut15-blaze")
    sess += _tdf_field_int("LLOG", now_s())
    sess += _tdf_field_str("MAIL", "localfut15@localhost")
    sess += _tdf_field_group("PDTL", bytes(pdtl))
    sess += _tdf_field_int("UID", persona)

    body = bytearray()
    body += _tdf_field_int("ANON", 0)
    body += _tdf_field_int("NTOS", 0)
    body += _tdf_field_group("SESS", bytes(sess))
    body += _tdf_field_int("SPAM", 1)
    body += _tdf_field_int("UNDR", 0)
    return bytes(body)


def _blaze_qos_data_group() -> bytes:
    body = bytearray()
    body += _tdf_field_int("DBPS", 0)
    body += _tdf_field_int("NATT", 0)
    body += _tdf_field_int("UBPS", 0)
    return bytes(body)


def _blaze_extended_data_minimal() -> bytes:
    """Minimal UserSessionExtendedData used in the captured login notifications."""
    body = bytearray()
    body += _tdf_field_int("HWFG", 0)
    body += _tdf_field_group("QDAT", _blaze_qos_data_group())
    body += _tdf_field_int("UATT", 0)
    return bytes(body)


def _blaze_notify_user_added() -> bytes:
    """UserSessions notification 2 (UserAdded), rebuilt with local identity."""
    persona = int(CFG["persona_id"])
    user = bytearray()
    user += _tdf_field_int("AID", persona)
    user += _tdf_field_int("ALOC", 1701729619)
    user += _tdf_field_blob("EXBB", b"")
    user += _tdf_field_int("EXID", 0)
    user += _tdf_field_int("ID", persona)
    user += _tdf_field_str("NAME", str(_persona_name()))
    # These FIFA-specific additions are present in the successful V3 packet.
    user += _tdf_field_str("NASP", "cem_ea_id")
    user += _tdf_field_int("ORIG", persona)
    user += _tdf_field_int("PIDI", 0)

    body = bytearray()
    body += _tdf_field_group("DATA", _blaze_extended_data_minimal())
    body += _tdf_field_group("USER", bytes(user))
    return bytes(body)


def _blaze_notify_login_session() -> bytes:
    """FIFA 15's UserSessions notification 8 captured immediately after c35/k10."""
    persona = int(CFG["persona_id"])
    body = bytearray()
    body += _tdf_field_int("BUID", persona)
    body += _tdf_field_object_id("CGID", 30722, 2, persona)
    body += _tdf_field_str("DSNM", str(_persona_name()))
    body += _tdf_field_str("KEY", "localfut15-blaze")
    body += _tdf_field_int("LAST", now_s())
    body += _tdf_field_str("MAIL", "localfut15@localhost")
    body += _tdf_field_str("NASP", "cem_ea_id")
    body += _tdf_field_int("PID", persona)
    body += _tdf_field_int("PLAT", 0)
    body += _tdf_field_int("UID", persona)
    body += _tdf_field_int("USTP", 0)
    body += _tdf_field_int("XREF", 0)
    return bytes(body)


def _blaze_notify_extended_data_update() -> bytes:
    """UserSessions notification 1, the small login-time extended-data update."""
    body = bytearray()
    body += _tdf_field_group("DATA", _blaze_extended_data_minimal())
    body += _tdf_field_int("USID", int(CFG["persona_id"]))
    return bytes(body)


def _blaze_notify_user_updated() -> bytes:
    """UserSessions notification 5 (UserUpdated)."""
    body = bytearray()
    body += _tdf_field_int("FLGS", 3)
    body += _tdf_field_int("ID", int(CFG["persona_id"]))
    return bytes(body)


def _blaze_login_notifications() -> list[tuple[int, int, bytes, str]]:
    # Exact order observed between the c35/k10 reply and Util.PostAuth.
    return [
        (30722, 2, _blaze_notify_user_added(), "UserSessions.UserAdded"),
        (30722, 8, _blaze_notify_login_session(), "UserSessions.LoginSession"),
        (30722, 1, _blaze_notify_extended_data_update(), "UserSessions.ExtendedDataUpdate"),
        (30722, 5, _blaze_notify_user_updated(), "UserSessions.UserUpdated"),
    ]


def _blaze_osdk_core_config() -> list[tuple[str, str]]:
    fut = int(CFG["fut_port"])
    easw = int(CFG["easw_port"])
    return [
        ("AUTH_TYPE", "NUCLEUS"),
        ("CONTENT_URL", f"http://127.0.0.1:{easw}/content"),
        ("CTL_UPDATE_URL", f"http://127.0.0.1:{easw}/ctl"),
        ("FIFA_POW_CONTENT_SERVER_URL", f"http://127.0.0.1:{fut}/"),
        ("FIFA_POW_NUCLEUS_PROXY_URL", f"http://127.0.0.1:{fut}/"),
        ("FIFA_POW_URL", f"http://127.0.0.1:{fut}/"),
        ("FUT_RS4_BASE_URL", f"http://127.0.0.1:{fut}/"),
        ("FUTDYNAMICMESSAGES_CUSTOMURL", f"127.0.0.1:{fut}"),
        ("FUTDYNAMICMESSAGES_URL_BASE", f"http://127.0.0.1:{fut}"),
        ("NUCLEUS_LOGIN_ENABLED", "1"),
        ("ONLINE/FUTDYNAMICMESSAGES_CUSTOMURL", f"127.0.0.1:{fut}"),
        ("ONLINE/FUTDYNAMICMESSAGES_TUTORIAL_MSG_URL", f"http://127.0.0.1:{fut}/"),
        ("ORIGIN_LOGIN_ENABLED", "1"),
        ("OSDK_AUTH_REQUIRED", "1"),
        ("OSDK_EASW_AUTH_URL", f"http://127.0.0.1:{easw}"),
        ("OSDK_EASW_EVENT_URL", f"http://127.0.0.1:{easw}"),
        ("OSDK_EASW_MEDIA_URL", f"http://127.0.0.1:{easw}"),
        ("OSDK_EASW_REQ_URL", f"http://127.0.0.1:{easw}"),
        ("ROSTERUPDATE_URL", f"http://127.0.0.1:{easw}/roster"),
        ("ROUTINGCFGFILE_URL", f"http://127.0.0.1:{easw}/routing"),
        ("USE_TOKEN_AUTH", "1"),
    ]


def _blaze_fetch_config_payload(cfid: str) -> bytes:
    items = _blaze_osdk_core_config() if cfid == "OSDK_CORE" else []
    body = bytearray()
    body += _tdf_field_map_str_str("CONF", items)
    body += _tdf_field_str("ID", cfid)
    body += _tdf_field_str("ITYP", "")
    body += _tdf_field_str("TOKN", "")
    return bytes(body)


def _blaze_telemetry_payload() -> bytes:
    body = bytearray()
    body += _tdf_field_str("ADRS", "127.0.0.1")
    body += _tdf_field_int("ANON", 0)
    body += _tdf_field_str("DISA", "1")
    body += _tdf_field_str("FILT", "")
    body += _tdf_field_int("LOC", 1701729619)
    body += _tdf_field_str("NOOK", "")
    body += _tdf_field_int("PORT", 9988)
    body += _tdf_field_int("SDLY", 0)
    body += _tdf_field_str("SESS", "")
    body += _tdf_field_str("SKEY", "")
    body += _tdf_field_int("SPCT", 0)
    body += _tdf_field_str("STIM", "")
    return bytes(body)


def _blaze_fifa_postauth_payload() -> bytes:
    pss = bytearray()
    pss += _tdf_field_int("PORT", 0)
    pss += _tdf_field_int("RPRT", 0)
    pss += _tdf_field_int("TIID", 0)

    tick = bytearray()
    tick += _tdf_field_str("ADRS", "127.0.0.1")
    tick += _tdf_field_int("PORT", 8999)
    tick += _tdf_field_str("SKEY", "")

    urop = bytearray()
    urop += _tdf_field_int("TMOP", 0)
    urop += _tdf_field_int("UID", int(CFG["persona_id"]))

    body = bytearray()
    body += _tdf_field_group("PSS", bytes(pss))
    body += _tdf_field_group("TELE", _blaze_telemetry_payload())
    body += _tdf_field_group("TICK", bytes(tick))
    body += _tdf_field_group("UROP", bytes(urop))
    return bytes(body)


def _blaze_entitlements_fifa15_payload() -> bytes:
    groups: list[bytes] = []
    for idx, gnam in enumerate(("FIFA15PCBoxContent", "FIFA14PC"), start=1):
        ent = bytearray()
        ent += _tdf_field_str("DEVI", "")
        ent += _tdf_field_str("GDAY", "")
        ent += _tdf_field_str("GNAM", gnam)
        ent += _tdf_field_int("ID", idx)
        ent += _tdf_field_int("ISCO", 0)
        ent += _tdf_field_int("PID", int(CFG["persona_id"]))
        ent += _tdf_field_str("PJID", "")
        ent += _tdf_field_int("PRCA", 0)
        ent += _tdf_field_str("PRID", "")
        ent += _tdf_field_int("STAT", 1)
        ent += _tdf_field_int("STRC", 0)
        ent += _tdf_field_str("TAG", "ONLINE_ACCESS")
        ent += _tdf_field_str("TDAY", "")
        ent += _tdf_field_int("TYPE", 1)
        ent += _tdf_field_int("UCNT", 0)
        ent += _tdf_field_int("VER", 0)
        groups.append(bytes(ent))
    return _tdf_field_list_groups("NLST", groups)


def _fire2_local_response(packet: Fire2Packet) -> tuple[bytes, str]:
    c, k = packet.component, packet.command

    # Util component - these shapes now mirror the successful FIFA 15 PC trace.
    if (c, k) == (9, 7):
        return _blaze_preauth_payload(), "Util.PreAuth"
    if (c, k) == (9, 2):
        return _tdf_field_int("STIM", now_s()), "Util.Ping"
    if (c, k) == (9, 1):
        cfid = _tdf_get_string(packet.payload, "CFID") or ""
        log.info("Util.FetchClientConfig CFID=%s", cfid)
        return _blaze_fetch_config_payload(cfid), f"Util.FetchClientConfig({cfid})"
    if (c, k) == (9, 8):
        return _blaze_fifa_postauth_payload(), "Util.PostAuth"
    if (c, k) == (9, 5):
        return _blaze_telemetry_payload(), "Util.GetTelemetryServer"
    if (c, k) == (9, 12):
        return _tdf_field_map_str_str("SMAP", [("FirstTimeFlag", "0")]), "Util.GetUserOptions"
    if (c, k) == (9, 10):
        key = _tdf_get_string(packet.payload, "KEY") or ""
        value = "0" if key == "FirstTimeFlag" else ""
        return _tdf_field_str("DATA", value) + _tdf_field_str("KEY", key), f"Util.GetUserOption({key})"
    if (c, k) in ((9, 22), (9, 28)):
        return b"", "Util.ClientState/Metrics"

    # FIFA 15 title-specific login bridge. The V3 capture proved this is not
    # an AUTH/EXTB/EXTI echo: the response is a FullLogin-style session object.
    if (c, k) == (35, 10):
        log.info(
            "FIFA35 login request: payload=%s; replying with captured-compatible local session",
            packet.payload.hex(),
        )
        return _blaze_fifa35_auth_bootstrap_payload(), "FIFA35.LoginSession"

    # FIFA 15 submits the terminal FUT game report through Blaze
    # GameReporting component 28 command 2. The immediate RPC is fieldless
    # success; completion arrives asynchronously as notification 114.
    if (c, k) == (28, 2):
        return b"", "GameReporting.SubmitOffline"

    # UserSessions / game bootstrap calls that returned no body in the trace.
    if (c, k) in (
        (30722, 20), (30722, 8),
        (21, 10),
        (15, 2),
        (10, 1),
        (25, 6),
        (11, 2600),
        (7, 15), (7, 3),
        (11, 1600),
        (0, 0),
    ):
        return b"", "captured-empty"

    # FIFA ticker/filter support.
    if (c, k) == (2249, 1):
        entry = bytearray()
        entry += _tdf_field_str("ID", "O_TKfilter")
        entry += _tdf_field_int("LOCF", 0)
        entry += _tdf_field_int("TOGG", 0)
        return _tdf_field_list_groups("LSST", [bytes(entry)]), "Ticker.GetSettings"
    if (c, k) == (2249, 2):
        entry = bytearray()
        entry += _tdf_field_str("ID", "O_SG_TCKR")
        # list<string> LSET
        lset = bytearray(_tdf_tag("LSET", _TDF_LIST))
        lset.append(_TDF_STRING)
        lset += _tdf_varint(1)
        lset += _tdf_str_value("O_TKfilter")
        entry += lset
        return _tdf_field_list_groups("LGRP", [bytes(entry)]), "Ticker.GetGroups"

    # Authentication. FIFA 15 asks for ListEntitlements (command 32) after the
    # title-specific login is complete.
    if c == 1 and k == 0x20:
        return _blaze_entitlements_fifa15_payload(), "Authentication.ListEntitlements"
    if c == 1 and k in (0x28, 0x32, 0x3C, 0x98, 0x0A):
        return _blaze_auth_payload(), f"Authentication.LocalLogin(0x{k:X})"
    if c == 1 and k in (0x1D, 0x30):
        return _blaze_entitlements_fifa15_payload(), f"Authentication.Entitlements(0x{k:X})"
    if c == 1 and k == 0x24:
        return _tdf_field_str("AUTH", STATE.token()), "Authentication.GetAuthToken"
    if c == 1 and k in (0x1E, 0x5A, 0x64, 0x6E):
        return _blaze_auth_payload(), f"Authentication.AccountPersona(0x{k:X})"
    if c == 1 and k == 0x46:
        return b"", "Authentication.Logout"

    return b"", "unknown-empty"


class BlazeOrHttpHandler(socketserver.BaseRequestHandler):
    """Port 10051 local Blaze listener (with legacy HTTP fallback)."""

    HTTP_PREFIXES = (b"GET ", b"POST ", b"PUT ", b"DELETE ", b"OPTIONS ", b"HEAD ")

    def handle(self) -> None:
        sock: socket.socket = self.request
        peer = self.client_address
        sock.settimeout(120)
        try:
            first = sock.recv(65536)
        except Exception:
            return
        if not first:
            return
        if first.startswith(self.HTTP_PREFIXES):
            self._http(sock, first)
            return

        buf = bytearray(first)
        while True:
            try:
                packet = _fire2_try_parse(buf)
            except Exception as exc:
                stamp = f"{int(time.time()*1000)}-{peer[1]}"
                raw_path = LOGS / f"blaze10051-unparsed-{stamp}.bin"
                raw_path.write_bytes(bytes(buf))
                log.exception("10051 Fire2 framing failed; saved %s: %s", raw_path.name, exc)
                return

            if packet is None:
                try:
                    more = sock.recv(65536)
                except socket.timeout:
                    log.info("10051 client %s:%s timed out", *peer)
                    return
                except (ConnectionResetError, ConnectionAbortedError):
                    return
                if not more:
                    return
                buf.extend(more)
                continue

            path = _save_fire2(packet, peer, "rx")
            log.info(
                "FIRE2 RX c=%d cmd=%d(0x%X) msg=%d type=%d payload=%d metadata=%d saved=%s",
                packet.component, packet.command, packet.command, packet.msg_num,
                packet.msg_type, len(packet.payload), len(packet.metadata), path.name,
            )

            # Fire2 Message=0; Reply=1; Ping=4; PingReply=5.
            if packet.msg_type == 4:
                reply = _fire2_build(packet.component, packet.command, packet.msg_num, 5, b"")
                sock.sendall(reply)
                log.info("FIRE2 TX PingReply msg=%d", packet.msg_num)
                continue
            if packet.msg_type != 0:
                continue

            payload, label = _fire2_local_response(packet)
            reply = _fire2_build(packet.component, packet.command, packet.msg_num, 1, payload)
            try:
                sock.sendall(reply)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            log.info(
                "FIRE2 TX %s c=%d cmd=%d msg=%d payload=%d",
                label, packet.component, packet.command, packet.msg_num, len(payload),
            )

            if label == "FIFA35.LoginSession":
                for ncomp, ncmd, npayload, nlabel in _blaze_login_notifications():
                    nframe = _fire2_build(ncomp, ncmd, 0, 2, npayload)
                    try:
                        sock.sendall(nframe)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                    log.info(
                        "FIRE2 TX NOTIFY %s c=%d cmd=%d payload=%d",
                        nlabel, ncomp, ncmd, len(npayload),
                    )

            if label == "GameReporting.SubmitOffline":
                reporting_id = _tdf_get_int_last(packet.payload, "GRID") or 0
                notification_payload = _game_reporting_result_notification_payload(reporting_id)
                notification = _fire2_build(28, 114, 0, 2, notification_payload)
                time.sleep(0.020)
                try:
                    sock.sendall(notification)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
                log.warning(
                    "GAME REPORTING RESULT NOTIFY c=28 cmd=114 reportId=%s payload=%s",
                    reporting_id, notification_payload.hex(),
                )

            if label == "unknown-empty":
                scout = _tdf_debug_summary(packet.payload)
                log.warning(
                    "CARDS-SCOUT Unhandled Blaze request c=%d cmd=%d(0x%X) msg=%d payload=%d :: %s",
                    packet.component, packet.command, packet.command, packet.msg_num, len(packet.payload), scout,
                )
                try:
                    scout_path = LOGS / f"cards-scout-c{packet.component}-k{packet.command}-m{packet.msg_num}-{int(time.time()*1000)}.json"
                    scout_path.write_text(json.dumps({
                        "component": packet.component, "command": packet.command, "commandHex": hex(packet.command),
                        "msgNum": packet.msg_num, "payloadHex": packet.payload.hex(), "summary": scout,
                    }, indent=2), encoding="utf-8")
                    log.warning("CARDS-SCOUT saved %s", scout_path.name)
                except Exception:
                    log.exception("CARDS-SCOUT failed to save diagnostic")

    def _http(self, sock: socket.socket, first: bytes) -> None:
        buf = bytearray(first)
        while b"\r\n\r\n" not in buf and len(buf) < 1024 * 1024:
            more = sock.recv(65536)
            if not more:
                break
            buf.extend(more)
        head, _, rest = bytes(buf).partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
        req = lines[0].split(" ")
        if len(req) < 2:
            return
        method, path = req[0], req[1]
        hdrs: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                hdrs[k.strip()] = v.strip()
        need = int(hdrs.get("Content-Length", "0") or "0")
        body = bytearray(rest)
        while len(body) < need:
            more = sock.recv(min(65536, need - len(body)))
            if not more:
                break
            body.extend(more)
        status, extra, out = route_fut(method, path, hdrs, bytes(body[:need]))
        reason = "OK" if status == 200 else "Error"
        response_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(out)),
            "Connection": "close",
            "X-UT-SID": STATE.sid(),
            **extra,
        }
        raw = [f"HTTP/1.1 {status} {reason}\r\n"] + [f"{k}: {v}\r\n" for k, v in response_headers.items()] + ["\r\n"]
        sock.sendall("".join(raw).encode("ascii") + out)


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ---- Local Origin LSX -----------------------------------------------------
# OriginSDK 9.x/10.x uses a server-first challenge, then AES-128-ECB encrypted
# hex frames. 0.1.1 incorrectly waited for a plaintext client request first,
# which deadlocked the SDK and could make FIFA exit on the language screen.


class OriginRandom:
    """Origin/EA SDK deterministic PRNG used for LSX session-key derivation."""

    def __init__(self, seed: int):
        self.seed = int(seed) & 0xFFFFFFFF

    def set_seed(self, seed: int) -> None:
        self.seed = int(seed) & 0xFFFFFFFF

    def next(self) -> int:
        # Same LCG used by the legacy Origin SDK.
        self.seed = (self.seed * 214013 + 2531011) & 0xFFFFFFFF
        return (self.seed >> 16) & 0x7FFF


class OriginCrypto:
    def __init__(self, seed: int = 0):
        self.key = bytes(range(16))
        self.set_key(seed)

    def set_key(self, seed: int) -> None:
        seed = int(seed) & 0xFFFFFFFF
        if seed == 0:
            self.key = bytes(range(16))
            return
        rng = OriginRandom(7)
        new_seed = (rng.next() + seed) & 0xFFFFFFFF
        rng.set_seed(new_seed)
        self.key = bytes((rng.next() & 0xFF) for _ in range(16))

    def encrypt(self, text: str) -> bytes:
        if Cipher is None:
            raise RuntimeError(f"cryptography package is unavailable: {_crypto_import_error}")
        padder = padding.PKCS7(128).padder()
        raw = padder.update(text.encode("utf-8")) + padder.finalize()
        enc = Cipher(algorithms.AES(self.key), modes.ECB()).encryptor()
        return enc.update(raw) + enc.finalize()

    def decrypt(self, ciphertext: bytes) -> str:
        if Cipher is None:
            raise RuntimeError(f"cryptography package is unavailable: {_crypto_import_error}")
        dec = Cipher(algorithms.AES(self.key), modes.ECB()).decryptor()
        padded = dec.update(ciphertext) + dec.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        raw = unpadder.update(padded) + unpadder.finalize()
        return raw.decode("utf-8")

    def challenge_response(self, challenge: str) -> str:
        response = self.encrypt(challenge).hex()
        b = response.encode("ascii")
        if len(b) < 2:
            raise ValueError("challenge response was too short")
        seed = (b[0] << 8) | b[1]
        self.set_key(seed)
        return response

    def set_session_from_response(self, response: str) -> int:
        b = response.encode("ascii", errors="strict")
        if len(b) < 2:
            raise ValueError("ChallengeResponse.response is too short")
        seed = (b[0] << 8) | b[1]
        self.set_key(seed)
        return seed


def _xml_attr(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _lsx_extract_request(request_xml: str) -> tuple[str, str, ET.Element | None]:
    rid = "0"
    name = "Unknown"
    op: ET.Element | None = None
    try:
        root = ET.fromstring(request_xml)
        req = root.find(".//Request")
        if req is not None:
            rid = req.attrib.get("id", rid)
            children = list(req)
            if children:
                op = children[0]
                name = op.tag.split("}")[-1]
    except Exception:
        pass
    return rid, name, op


def _lsx_response_envelope(rid: str, inner: str, sender: str = "EbisuSDK") -> str:
    return f'<LSX><Response id="{_xml_attr(rid)}" sender="{_xml_attr(sender)}">{inner}</Response></LSX>'


def _lsx_xml_response(request_xml: str) -> str:
    rid, name, op = _lsx_extract_request(request_xml)
    player = str(_persona_name())
    nucleus = str(CFG["nucleus_id"])
    persona = str(CFG["persona_id"])

    if name == "GetConfig":
        services = (
            ("EbisuSDK", "SDK"),
            ("EbisuSDK", "PROFILE"),
            ("XMPP", "PRESENCE"),
            ("XMPP", "FRIENDS"),
            ("Commerce", "COMMERCE"),
            ("EbisuSDK", "RECENTPLAYER"),
            ("EbisuSDK", "IGO"),
            ("EbisuSDK", "MISC"),
            ("EALS", "LOGIN"),
            ("EbisuSDK", "UTILITY"),
            ("XMPP", "XMPP"),
            ("XMPP", "CHAT"),
            ("EbisuSDK", "IGO_EVENT"),
            ("EALS", "EALS_EVENTS"),
            ("EbisuSDK", "LOGIN_EVENT"),
            ("XMPP", "INVITE_EVENT"),
            ("EbisuSDK", "PROFILE_EVENT"),
            ("XMPP", "PRESENCE_EVENT"),
            ("XMPP", "FRIENDS_EVENT"),
            ("Commerce", "COMMERCE_EVENT"),
            ("XMPP", "CHAT_EVENT"),
            ("EbisuSDK", "DOWNLOAD_EVENT"),
            ("EbisuSDK", "PERMISSION"),
            ("EbisuSDK", "RESOURCES"),
            ("EbisuSDK", "BLOCKED_USERS"),
            ("EbisuSDK", "BLOCKED_USER_EVENT"),
            ("EbisuSDK", "GET_USERID"),
            ("EbisuSDK", "ONLINE_STATUS_EVENT"),
            ("EbisuSDK", "ACHIEVEMENT"),
            ("EbisuSDK", "ACHIEVEMENT_EVENT"),
            ("EbisuSDK", "BROADCAST_EVENT"),
            ("PI", "PROGRESSIVE_INSTALLATION"),
            ("PI", "PROGRESSIVE_INSTALLATION_EVENT"),
            ("EbisuSDK", "CONTENT"),
        )
        inner = '<GetConfigResponse>' + ''.join(
            f'<Service Name="{name}" Facility="{facility}" />' for name, facility in services
        ) + '</GetConfigResponse>'
    elif name == "GetSettings":
        inner = ('<GetSettingsResponse Language="en_US" Environment="production" '
                 'IsIGOAvailable="false" IsIGOEnabled="false" '
                 'IsTelemetryEnabled="false" IsManualOffline="false" />')
    elif name == "GetSetting":
        setting = ""
        if op is not None:
            setting_id = op.attrib.get("SettingId", "")
            setting = {
                "LANGUAGE": "en_US",
                "ENVIRONMENT": "production",
                "IS_IGO_AVAILABLE": "false",
                "IS_IGO_ENABLED": "false",
                "IS_TELEMETRY_ENABLED": "false",
                "IS_MANUAL_OFFLINE": "false",
            }.get(setting_id, "")
        inner = f'<GetSettingResponse Setting="{_xml_attr(setting)}" />'
    elif name == "GetInternetConnectedState":
        inner = '<InternetConnectedState connected="1" />'
    elif name == "GetUtcTime":
        utc = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        inner = f'<GetUtcTimeResponse Time="{utc}" />'
    elif name == "GetAuthToken":
        inner = '<AuthToken value="LOCAL-FUT15-ACCESS" />'
    elif name == "GetAuthCode":
        inner = '<AuthCode value="LOCAL-FUT15-AUTH-CODE" />'
    elif name == "GetProfile":
        inner = (f'<GetProfileResponse UserIndex="0" UserId="{_xml_attr(nucleus)}" '
                 f'PersonaId="{_xml_attr(persona)}" Persona="{_xml_attr(player)}" AvatarId="" '
                 'Country="PT" IsUnderAge="false" IsSubscriber="false" '
                 'IsTrialSubscriber="false" SubscriberLevel="0" GeoCountry="PT" '
                 'CommerceCountry="PT" CommerceCurrency="EUR" IsSteamSubscriber="false" />')
    elif name == "GetBlockList":
        inner = '<GetBlockListResponse />'
    elif name == "QueryFriends":
        inner = '<QueryFriendsResponse />'
    elif name == "QueryAreFriends":
        inner = '<QueryAreFriendsResponse />'
    elif name in ("QueryContent",):
        inner = '<QueryContentResponse />'
    elif name in ("QueryEntitlements",):
        inner = '<QueryEntitlementsResponse />'
    elif name == "GetPresence":
        inner = '<GetPresenceResponse />'
    elif name == "QueryPresence":
        inner = '<QueryPresenceResponse />'
    elif name == "GetWalletBalance":
        inner = '<GetWalletBalanceResponse Balance="0" Currency="EUR" />'
    elif name == "GetGameInfo":
        # Legacy OriginSDK/FIFA 15 asks for individual title-state values.
        # Returning an empty GetGameInfoResponse makes the client interpret
        # UPTODATE as false and show the mandatory-update dialog.
        game_info_id = ""
        if op is not None:
            game_info_id = op.attrib.get("GameInfoId", "").upper()
        game_info_values = {
            "UPTODATE": "true",
            "LANGUAGES": "en_US,pt_PT,fr_FR,de_DE,es_ES,it_IT",
            "FREETRIAL": "false",
            "EXPIRATION": "0000-00-00T00:00:00",
            "EXPIRATION_DURATION": "0",
            "INSTALLED_VERSION": "1.0.0.0",
            "INSTALLED_LANGUAGE": "en_US",
            "AVAILABLE_VERSION": "1.0.0.0",
            "DISPLAY_NAME": "EA SPORTS FIFA 15",
            "FULLGAME_PURCHASED": "true",
            "FULLGAME_IS_RELEASED": "true",
            "FULLGAME_RELEASE_DATE": "2014-09-25T00:00:00",
            "MAX_GROUP_SIZE": "22",
            "ENTITLEMENT_SOURCE": "LOCAL",
        }
        game_info = game_info_values.get(game_info_id, "")
        log.info("LSX GetGameInfo %s -> %s", game_info_id or "<missing>", game_info)
        inner = f'<GetGameInfoResponse GameInfo="{_xml_attr(game_info)}" />'
    elif name == "GetAllGameInfo":
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        inner = (f'<GetAllGameInfoResponse UpToDate="true" '
                 'Languages="en_US,pt_PT,fr_FR,de_DE,es_ES,it_IT" FreeTrial="false" '
                 'FullGamePurchased="true" FullGameReleased="true" '
                 'FullGameReleaseDate="2014-09-25T00:00:00" Expiration="" '
                 f'SystemTime="{now}" HasExpiration="false" InstalledVersion="1.0.0.0" '
                 'InstalledLanguage="en_US" AvailableVersion="1.0.0.0" '
                 'DisplayName="EA SPORTS FIFA 15" MaxGroupSize="22" EntitlementSource="LOCAL" />')
    elif name == "RequestLicense":
        # This local shim does not manufacture a third-party service token.
        # The legacy ItsAMe_Origin path used by this setup only needs an LSX reply;
        # keep it intentionally minimal and local.
        inner = '<RequestLicenseResponse />'
    else:
        # Most setter/notification calls use ErrorSuccess in OriginSDK. Keeping
        # the response explicit also makes unsupported calls obvious in the log.
        inner = '<ErrorSuccess Code="0" Description="Local FUT success" />'
        log.warning("LSX unmodelled request %s; returning generic ErrorSuccess", name)

    return _lsx_response_envelope(rid, inner)


def _recv_nul_frame(sock: socket.socket, buffer: bytearray) -> bytes | None:
    while b"\x00" not in buffer:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        buffer.extend(chunk)
    idx = buffer.index(0)
    frame = bytes(buffer[:idx])
    del buffer[: idx + 1]
    return frame


def _send_plain_frame(sock: socket.socket, xml: str) -> None:
    sock.sendall(xml.encode("utf-8") + b"\x00")


def _send_encrypted_frame(sock: socket.socket, crypto: OriginCrypto, xml: str) -> None:
    payload = crypto.encrypt(xml).hex().encode("ascii") + b"\x00"
    sock.sendall(payload)


class LSXHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        sock: socket.socket = self.request
        sock.settimeout(30)
        peer = self.client_address
        log.info("Origin LSX client connected from %s:%s", *peer)
        buffer = bytearray()

        if Cipher is None:
            log.error("Origin LSX requires the Python 'cryptography' package: %s", _crypto_import_error)
            return

        # 1) Server must speak first. This is the critical fix over 0.1.1.
        challenge_key = secrets.token_hex(16).upper()
        challenge = (f'<LSX><Event sender="EALS"><Challenge key="{challenge_key}" '
                     'version="3" build="10.6.1.8" /></Event></LSX>')
        try:
            _send_plain_frame(sock, challenge)
            log.info("LSX challenge sent to %s:%s key=%s", *peer, challenge_key)

            # 2) ChallengeResponse is still plaintext/NUL-delimited.
            frame = _recv_nul_frame(sock, buffer)
            if frame is None:
                log.warning("LSX client disconnected before ChallengeResponse")
                return
            text = frame.decode("utf-8", errors="replace")
            log.info("LSX plaintext handshake request: %s", text[:3000])
            rid, name, op = _lsx_extract_request(text)
            if name != "ChallengeResponse" or op is None:
                log.warning("Expected ChallengeResponse, received %s", name)
                return
            response = op.attrib.get("response", "")
            returned_key = op.attrib.get("key", "")
            if len(response) < 2:
                log.warning("LSX ChallengeResponse had no usable response attribute")
                return

            # Exact legacy LSX challenge behavior, matching the open-source
            # Maxima Origin/LSX implementation:
            #   1) ChallengeResponse.response must be AES-128-ECB/PKCS7 of the
            #      server Challenge.key using the primary key 00..0f.
            #   2) ChallengeResponse.key is a *client-generated* MD5-ish nonce.
            #      The server encrypts THAT value with the primary key and returns
            #      it as ChallengeAccepted.response.
            #   3) Protocol version 2 keeps the primary 00..0f key for every
            #      subsequent encrypted LSX frame. Version 3 derives a secondary
            #      key from the first two ASCII bytes of the accept response.
            protocol_version = op.attrib.get("version", "3")
            primary_crypto = OriginCrypto(0)
            expected_response = primary_crypto.encrypt(challenge_key).hex()
            if response.lower() == expected_response.lower():
                log.info("LSX challenge response validated for protocol %s", protocol_version)
            else:
                log.warning("LSX challenge response did not validate; expected=%s got=%s", expected_response, response)
                return

            if not returned_key:
                log.warning("LSX ChallengeResponse is missing the client key attribute")
                return
            log.info("LSX client key attribute: %s", returned_key)

            # Server-side mutual challenge response. This was the missing piece in
            # 0.1.4/0.1.5: echoing the client's response is not valid for FIFA 15.
            accept_response = primary_crypto.encrypt(returned_key).hex()

            if protocol_version == "2":
                seed = 0
                crypto = OriginCrypto(0)
                log.info("LSX protocol 2 retaining primary OriginSDK AES key")
            elif protocol_version == "3":
                rb = accept_response.encode("ascii")
                seed = (rb[0] << 8) | rb[1]
                crypto = OriginCrypto(seed)
                log.info("LSX protocol 3 using ChallengeAccepted-derived session key (seed=%d)", seed)
            else:
                log.warning("Unsupported LSX ChallengeResponse version %s", protocol_version)
                return

            accepted = _lsx_response_envelope(
                rid,
                f'<ChallengeAccepted response="{_xml_attr(accept_response)}" />',
                sender="EALS",
            )
            _send_plain_frame(sock, accepted)
            log.info("LSX challenge accepted for %s:%s; protocol=%s session seed=%d", *peer, protocol_version, seed)

            # EA Desktop/Origin also exposes current login state as an LSX event.
            # FIFA 15 checks this before it attempts Blaze authentication.
            login_event = (
                '<LSX><Event sender="EbisuSDK">'
                '<Login IsLoggedIn="true" UserIndex="0" LoginReasonCode="ALREADY_ONLINE" />'
                '</Event></LSX>'
            )
            try:
                _send_encrypted_frame(sock, crypto, login_event)
                log.info("LSX local signed-in Login event sent to %s:%s", *peer)
            except Exception:
                log.exception("Unable to send LSX Login event to %s:%s", *peer)

            # FIFA 15 can remain in an offline match for long periods without sending
            # any LSX requests. After authentication, keep the connection open
            # indefinitely and let the client close it normally.
            sock.settimeout(None)
            while True:
                frame = _recv_nul_frame(sock, buffer)
                if frame is None:
                    break
                if not frame:
                    continue
                try:
                    encrypted = bytes.fromhex(frame.decode("ascii"))
                    request_xml = crypto.decrypt(encrypted)
                except Exception as exc:
                    stamp = f"{int(time.time()*1000)}-{peer[1]}"
                    (LOGS / f"lsx-decode-fail-{stamp}.bin").write_bytes(frame)
                    log.exception("LSX encrypted frame could not be decoded/decrypted: %s", exc)
                    break

                log.info("LSX decrypted request: %s", request_xml[:6000])
                response_xml = _lsx_xml_response(request_xml)
                log.info("LSX encrypted response: %s", response_xml[:6000])
                _send_encrypted_frame(sock, crypto, response_xml)

        except socket.timeout:
            log.info("Origin LSX client %s:%s timed out/closed", *peer)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            log.info("Origin LSX client %s:%s disconnected", *peer)
        except Exception:
            log.exception("Origin LSX handler failed for %s:%s", *peer)

def start_server_thread(server: Any, name: str) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, name=name, daemon=True)
    t.start()
    return t


def _candidate_ports(preferred: int) -> list[int]:
    """Return deterministic localhost fallback ports for Windows reserved ranges."""
    out = [int(preferred)]
    for bump in (10000, 20000, 30000, 40000, 50000):
        p = int(preferred) + bump
        if 1024 <= p <= 65535 and p not in out:
            out.append(p)
    return out


def _bind_service(host: str, cfg_key: str, label: str, server_cls: Any, handler_cls: Any,
                  *, strict: bool = False) -> Any:
    preferred = int(CFG[cfg_key])
    attempts = [preferred] if strict else _candidate_ports(preferred)
    errors: list[tuple[int, OSError]] = []
    for port in attempts:
        try:
            server = server_cls((host, int(port)), handler_cls)
            CFG[cfg_key] = int(port)
            if port == preferred:
                log.info("Bound %-12s on %s:%d", label, host, port)
            else:
                log.warning(
                    "Windows rejected preferred %-12s port %d; using localhost fallback %d",
                    label, preferred, port,
                )
            return server
        except OSError as exc:
            errors.append((port, exc))
            winerr = getattr(exc, "winerror", None)
            log.warning(
                "Bind failed for %-12s %s:%d: %s%s",
                label, host, port, exc,
                f" (WinError {winerr})" if winerr else "",
            )
    detail = "; ".join(f"{p}: {e}" for p, e in errors)
    raise OSError(f"{label} could not bind any permitted localhost port ({detail})")


def _tcp_listener_present(host: str, port: int, timeout: float = 0.25) -> bool:
    """Return True when something is already accepting TCP connections locally."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _prepare_lsx(host: str) -> tuple[Any | None, str]:
    """Use an existing EA/Origin LSX listener when present, otherwise host ours.

    EA App/Origin legitimately owns TCP 3216 on some Windows installs. A second
    bind can surface as WSAEACCES/10013, so treating every bind failure as fatal
    incorrectly prevents Local FUT from starting.
    """
    port = int(CFG["lsx_port"])

    # Probe first so we do not disturb a real EA App/Origin LSX service.
    if _tcp_listener_present(host, port):
        log.info(
            "Existing Origin/EA LSX listener detected on %s:%d; using external LSX passthrough",
            host, port,
        )
        return None, "external"

    try:
        server = ThreadingTCPServer((host, port), LSXHandler)
        log.info("Bound %-12s on %s:%d", "Origin LSX", host, port)
        return server, "local"
    except OSError as exc:
        winerr = getattr(exc, "winerror", None)
        log.warning(
            "Bind failed for %-12s %s:%d: %s%s",
            "Origin LSX", host, port, exc,
            f" (WinError {winerr})" if winerr else "",
        )

        # An exclusive owner can race the initial probe. Recheck after bind.
        if _tcp_listener_present(host, port, timeout=0.5):
            log.info(
                "Origin/EA LSX became reachable on %s:%d after bind failure; using external LSX passthrough",
                host, port,
            )
            return None, "external"

        # Do not block the whole Local FUT stack for an OS-level 3216
        # reservation. EA-MITM already bypasses FIFA 15's legacy Origin launch
        # failure check, so continue in degraded mode and let the game tell us
        # whether this installation actually requires LSX. This is safer than
        # mutating Windows excluded-port ranges from an installer.
        log.error(
            "Origin LSX %s:%d is unavailable and no external listener is reachable; "
            "continuing without LSX so FUT tracing can still start", host, port
        )
        return None, "unavailable"


def _write_runtime_routing(host: str, *, lsx_mode: str = "local") -> None:
    """Write the chosen ports before FIFA starts so the local hook follows fallbacks."""
    game_root = ROOT.parent
    legacy = int(CFG["legacy_fut_port"])
    fut = int(CFG["fut_port"])
    blaze = int(CFG["blaze_port"])
    qos = int(CFG["qos_port"])
    easw = int(CFG["easw_port"])
    redir = int(CFG["redirect_port"])

    cl = f"""; FIFA 15 Local FUT v0.2.39 - generated localhost routing\nFUT_ENABLE_MENU = 1\nFUT_TARGET_HOSTNAME = {host}\nFUT_TARGET_PORT = {legacy}\nFUT_RS4_BASE_URL = http://{host}:{legacy}/\nFIFA_POW_NUCLEUS_PROXY_URL = http://{host}:{legacy}/\n"""
    (game_root / "cl.ini").write_text(cl, encoding="utf-8")

    # Keep SourcePort values on the original FIFA 15 ports so hard-coded
    # calls are translated to whichever safe localhost ports were chosen.
    mitm = f"""; FIFA 15 Local FUT v0.2.39 - generated localhost routing
; Local-only routing: no external revival hostnames or third-party endpoints.
[Hook]
InitDelay=3000

[Origin]
LaunchFailureCheckRva=0x0390AD3F

[ProtoSSL]
Connect=0x0000000143066524
Send=0
Recv=0

[Redirect]
Count=6

Redirect.0.Hostname=spring14.gosredirector.ea.com
Redirect.0.Address={host}
Redirect.0.Port={redir}
Redirect.0.Secure=0

Redirect.1.Hostname={host}
Redirect.1.SourcePort=10051
Redirect.1.Address={host}
Redirect.1.Port={blaze}
Redirect.1.Secure=0

Redirect.2.Hostname={host}
Redirect.2.SourcePort=17502
Redirect.2.Address={host}
Redirect.2.Port={qos}
Redirect.2.Secure=0

Redirect.3.Hostname={host}
Redirect.3.SourcePort=42232
Redirect.3.Address={host}
Redirect.3.Port={easw}
Redirect.3.Secure=0

Redirect.4.Hostname={host}
Redirect.4.SourcePort=8199
Redirect.4.Address={host}
Redirect.4.Port={fut}
Redirect.4.Secure=0

Redirect.5.Hostname={host}
Redirect.5.SourcePort=8099
Redirect.5.Address={host}
Redirect.5.Port={legacy}
Redirect.5.Secure=0
"""
    (game_root / "EA-MITM.ini").write_text(mitm, encoding="utf-8")

    ports = {
        "lsx_port": int(CFG["lsx_port"]),
        "lsx_mode": str(lsx_mode),
        "redirect_port": redir,
        "blaze_port": blaze,
        "qos_port": qos,
        "easw_port": easw,
        "fut_port": fut,
        "legacy_fut_port": legacy,
    }
    (RUNTIME_ROOT / "runtime_ports.json").write_text(json.dumps(ports, indent=2), encoding="utf-8")
    log.info("Runtime port map: %s", ports)


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    host = args.host
    runtime_ports = RUNTIME_ROOT / "runtime_ports.json"
    try:
        runtime_ports.unlink(missing_ok=True)
    except Exception:
        pass

    servers: list[Any] = []
    try:
        # Bind independently so one Windows excluded/reserved port does not
        # kill the entire stack. FIFA-routed services may use deterministic
        # fallbacks. Origin/EA LSX is special: if EA App/Origin already owns
        # 3216, coexist with that listener instead of attempting a second bind.
        fut = _bind_service(host, "fut_port", "FUT/POW", ThreadingHTTPServer, FutHandler)
        servers.append(fut)
        legacy_fut = _bind_service(host, "legacy_fut_port", "FUT compat", ThreadingHTTPServer, FutHandler)
        servers.append(legacy_fut)
        redir = _bind_service(host, "redirect_port", "Redirector", ThreadingHTTPServer, RedirectHandler)
        servers.append(redir)
        qos = _bind_service(host, "qos_port", "QoS HTTP", ThreadingHTTPServer, QosHandler)
        servers.append(qos)
        easw = _bind_service(host, "easw_port", "EASW HTTP", ThreadingHTTPServer, EaswHandler)
        servers.append(easw)
        blaze = _bind_service(host, "blaze_port", "Game/Blaze", ThreadingTCPServer, BlazeOrHttpHandler)
        servers.append(blaze)
        lsx, lsx_mode = _prepare_lsx(host)
        if lsx is not None:
            servers.append(lsx)
        _write_runtime_routing(host, lsx_mode=lsx_mode)
    except (OSError, PermissionError) as exc:
        for srv in servers:
            try:
                srv.server_close()
            except Exception:
                pass
        log.error("Local service startup failed: %s", exc)
        if "Origin LSX" in str(exc):
            log.error("Origin LSX 3216 is blocked and no EA/Origin listener is reachable. Run PORT_DIAGNOSTICS.cmd.")
        return 2
    except Exception as exc:
        for srv in servers:
            try:
                srv.server_close()
            except Exception:
                pass
        log.exception("Could not prepare dynamic localhost routing: %s", exc)
        return 2

    start_server_thread(fut, f"FUT-{CFG['fut_port']}")
    start_server_thread(legacy_fut, f"FUT-{CFG['legacy_fut_port']}-compat")
    start_server_thread(redir, f"Redirector-{CFG['redirect_port']}")
    start_server_thread(qos, f"QoS-{CFG['qos_port']}")
    start_server_thread(easw, f"EASW-{CFG['easw_port']}")
    start_server_thread(blaze, f"Blaze-{CFG['blaze_port']}")
    if lsx is not None:
        start_server_thread(lsx, f"OriginLSX-{CFG['lsx_port']}")

    print("=" * 70)
    print(f"{APP_NAME} {VERSION} READY")
    if lsx_mode == "external":
        print(f" Origin LSX : {host}:{CFG['lsx_port']} (EA App/Origin external listener)")
    elif lsx_mode == "unavailable":
        print(f" Origin LSX : {host}:{CFG['lsx_port']} (unavailable - continuing in degraded mode)")
    else:
        print(f" Origin LSX : {host}:{CFG['lsx_port']} (Local FUT listener)")
    print(f" Redirector : {host}:{CFG['redirect_port']}")
    print(f" Game/Blaze : {host}:{CFG['blaze_port']}")
    print(f" QoS HTTP   : http://{host}:{CFG['qos_port']}/")
    print(f" EASW HTTP  : http://{host}:{CFG['easw_port']}/")
    print(f" FUT/POW    : http://{host}:{CFG['fut_port']}/")
    print(f" FUT compat : http://{host}:{CFG['legacy_fut_port']}/")
    print(f" Local club : {_club_name()} / {_persona_name()} / {STATE.credits()} coins")
    print(f" State/logs : {RUNTIME_ROOT}")
    print(" Windows-reserved FIFA ports are automatically remapped locally.")
    print(" Keep this window open while FIFA 15 is running.")
    print("=" * 70)
    log.info("All localhost services ready")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            runtime_ports.unlink(missing_ok=True)
        except Exception:
            pass
        for s in servers:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
