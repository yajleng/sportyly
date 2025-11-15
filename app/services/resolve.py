from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, List
import re

from ..clients.apisports import ApiSportsClient, League

# quick normalization
def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(university|college|the|fc|sc|club|state)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

def _ratio(a: str, b: str) -> float:
    # lightweight similarity: token overlap Jaccard + prefix bonus
    ta, tb = set(a.split()), set(b.split())
    inter = len(ta & tb)
    union = max(1, len(ta | tb))
    j = inter / union
    if a and b and (a[0] == b[0]):
        j += 0.05
    return min(j, 1.0)

_ALIAS: Dict[str, str] = {}  # normalized -> original seen
def remember_alias(name: str) -> None:
    _ALIAS[_norm(name)] = name

def resolve_fixture_id(
    client: ApiSportsClient,
    *,
    league: League,
    date: str,
    home: Optional[str] = None,
    away: Optional[str] = None,
    league_id_override: Optional[int] = None,
    season: Optional[int] = None,
) -> Dict[str, Any]:
    fx = client.fixtures_by_date(league=league, date=date, season=season, league_id=league_id_override)
    games = fx.get("response") or fx.get("results") or []
    if league == "soccer":
        rows = [{
            "fixture_id": int(g["fixture"]["id"]),
            "home": g["teams"]["home"]["name"],
            "away": g["teams"]["away"]["name"],
        } for g in games]
    else:
        rows = []
        for g in games:
            fid = g.get("id") or (g.get("game") or {}).get("id") or (g.get("fixture") or {}).get("id")
            teams = g.get("teams") or {}
            h = (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name")
            a = (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name")
            if fid and h and a:
                rows.append({"fixture_id": int(fid), "home": h, "away": a})

    target_h = _norm(home or "")
    target_a = _norm(away or "")

    best: Tuple[int, float, Dict[str, Any]] = (-1, -1.0, {})
    cands: List[Dict[str, Any]] = []
    for r in rows:
        remember_alias(r["home"]); remember_alias(r["away"])
        score = 0.0
        if target_h:
            score += _ratio(target_h, _norm(r["home"]))
        if target_a:
            score += _ratio(target_a, _norm(r["away"]))
        cands.append({"fixture_id": r["fixture_id"], "home": r["home"], "away": r["away"], "score": round(score, 3)})
        if score > best[1]:
            best = (r["fixture_id"], score, r)

    picked_reason = None
    picked = best[0] if best[1] >= 1.2 if (target_h and target_a) else best[1] >= 0.6 else None  # threshold tuned
    if picked:
        picked_reason = "High-confidence team match."
    return {"fixture_id": picked, "candidates": cands, "picked_reason": picked_reason}
