# app/services/markets.py
from __future__ import annotations

from typing import Optional

# Expecting your existing map file. Keep it minimal here:
# MAP structure assumption:
# MAP[league]["bets"][bet_id] = {"alias": "...", "periods": ["game","1h","2h","1q","2q","3q","4q"]}
from app.spec.apisports_map import MAP


def resolve_bet_id(league: str, market_alias: Optional[str], period: Optional[str]) -> Optional[int]:
    """
    Resolve a friendly (market_alias, period) -> bet_id using apisports_map.
    - market_alias examples: "spread", "total", "moneyline", "player_points", "player_assists", etc.
    - period examples: "game","1h","2h","1q","2q","3q","4q"
    """
    if not market_alias:
        return None

    league = league.lower()
    key = market_alias.lower().strip()
    per = (period or "game").lower().strip()

    sport = MAP.get(league) or {}
    bets = (sport.get("bets") or {})

    # Exact alias + period
    for bid, meta in bets.items():
        try:
            alias = (meta.get("alias") or "").lower()
            periods = [p.lower() for p in (meta.get("periods") or ["game"])]
        except Exception:
            continue
        if alias == key and per in periods:
            return int(bid)

    # Fallback: alias only
    for bid, meta in bets.items():
        try:
            alias = (meta.get("alias") or "").lower()
        except Exception:
            continue
        if alias == key:
            return int(bid)

    return None
