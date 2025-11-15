# app/services/markets.py
from __future__ import annotations

from typing import Optional, Dict, Any
import json
import importlib
import pkgutil
import os
import pathlib

# -----------------------------------------------------------------------------
# Resilient market map loader
# -----------------------------------------------------------------------------

# Search order:
# 1) Python module app.spec.apisports_map with symbol MAP (or APISPORTS_MAP / BETS)
# 2) JSON resource app/spec/apisports_map.json (dict format)
# 3) Env var APISPORTS_MAP_JSON pointing to a JSON file
# If none found, fall back to empty mapping (aliases will simply not resolve).
# Expected normalized shape after load:
#   MAP[league]["bets"][bet_id] = {
#       "alias": "spread|total|moneyline|player_points|...",
#       "periods": ["game","1h","2h","1q","2q","3q","4q"]  # optional
#   }
# -----------------------------------------------------------------------------

_MAP: Dict[str, Any] | None = None

def _load_from_module() -> Dict[str, Any] | None:
    try:
        mod = importlib.import_module("app.spec.apisports_map")
    except Exception:
        return None

    # Accept a few possible symbol names
    for name in ("MAP", "APISPORTS_MAP", "BETS"):
        if hasattr(mod, name):
            obj = getattr(mod, name)
            if isinstance(obj, dict):
                return obj
    # Some repos export a function like get_map()
    for name in ("get_map", "load_map"):
        fn = getattr(mod, name, None)
        if callable(fn):
            try:
                obj = fn()
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
    return None

def _load_from_json_resource() -> Dict[str, Any] | None:
    # Look for app/spec/apisports_map.json packaged with the app
    try:
        pkg = importlib.import_module("app.spec")
    except Exception:
        return None

    # Use pkgutil to check for the resource
    try:
        data = pkgutil.get_data(pkg.__name__, "apisports_map.json")
        if not data:
            return None
        obj = json.loads(data.decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None

def _load_from_envfile() -> Dict[str, Any] | None:
    path = os.environ.get("APISPORTS_MAP_JSON")
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None

def _normalize_map(m: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure consistent keys, lowercased leagues/aliases/periods.
    out: Dict[str, Any] = {}
    for league, payload in (m or {}).items():
        bets = (payload or {}).get("bets") or {}
        nbets: Dict[str, Any] = {}
        for bid, meta in bets.items():
            try:
                bid_int = int(bid)
            except Exception:
                # Skip non-numeric keys
                continue
            alias = (meta.get("alias") or "").strip().lower()
            periods = [str(p).strip().lower() for p in (meta.get("periods") or ["game"])]
            nbets[str(bid_int)] = {"alias": alias, "periods": periods}
        out[league.strip().lower()] = {"bets": nbets}
    return out

def _load_map() -> Dict[str, Any]:
    global _MAP
    if _MAP is not None:
        return _MAP

    m = _load_from_module()
    if m is None:
        m = _load_from_json_resource()
    if m is None:
        m = _load_from_envfile()
    if m is None:
        m = {}

    _MAP = _normalize_map(m)
    return _MAP

# -----------------------------------------------------------------------------
# Public resolver
# -----------------------------------------------------------------------------

def resolve_bet_id(league: str, market_alias: Optional[str], period: Optional[str]) -> Optional[int]:
    """
    Resolve a friendly (market_alias, period) -> bet_id using the market map.
    - market_alias examples: "spread", "total", "moneyline",
      "player_points", "player_assists", "player_rebounds", etc.
    - period examples: "game","1h","2h","1q","2q","3q","4q" (league-specific)
    Returns an integer bet_id, or None if not found.
    """
    if not market_alias:
        return None

    league_key = (league or "").strip().lower()
    alias_key = market_alias.strip().lower()
    period_key = (period or "game").strip().lower()

    MAP = _load_map()  # lazy load; safe if file/module missing
    sport = MAP.get(league_key) or {}
    bets = (sport.get("bets") or {})

    # 1) exact alias + period match
    for bid_str, meta in bets.items():
        alias = (meta.get("alias") or "")
        periods = meta.get("periods") or ["game"]
        if alias == alias_key and period_key in periods:
            try:
                return int(bid_str)
            except Exception:
                continue

    # 2) fallback: alias only
    for bid_str, meta in bets.items():
        alias = (meta.get("alias") or "")
        if alias == alias_key:
            try:
                return int(bid_str)
            except Exception:
                continue

    return None

# Optional helper: list known markets for debugging
def list_markets(league: str) -> Dict[str, Any]:
    MAP = _load_map()
    league_key = (league or "").strip().lower()
    return MAP.get(league_key, {})
