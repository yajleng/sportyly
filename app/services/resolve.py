# app/services/resolve.py
from __future__ import annotations
from typing import Optional, Tuple, Dict, Any, List
import re

from ..clients.apisports import ApiSportsClient, League

def _norm(s: str) -> str:
    # simple, dependency-free normalizer
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""

def _extract_game_fields(league: League, g: Dict[str, Any]) -> Tuple[Optional[int], str, str, str]:
    """
    Return (fixture_id, date_iso, home_name, away_name) in a cross-sport way.
    """
    if league == "soccer":
        try:
            fid = g["fixture"]["id"]
            dt = g["fixture"]["date"]
            home = g["teams"]["home"]["name"]
            away = g["teams"]["away"]["name"]
            return fid, dt, home, away
        except Exception:
            return None, "", "", ""
    else:
        # american-football + (future) basketball share similar v1-ish shapes
        fid = g.get("id") or g.get("game", {}).get("id") or g.get("fixture", {}).get("id")
        dt = g.get("date") or g.get("game", {}).get("date") or ""
        teams = g.get("teams") or {}
        home = (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name") or ""
        away = (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name") or ""
        return fid, dt, home, away

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
    """
    Look up fixtures on a date and try to match by team names.
    Returns:
      {
        "fixture_id": int | None,
        "candidates": [ { "fixture_id": int, "date": str, "home": str, "away": str, "score": float } ],
        "picked_reason": str
      }
    """
    fx = client.fixtures_by_date(
        league=league,
        date=date,
        season=season,
        league_id=league_id_override,
    )
    items: List[Dict[str, Any]] = fx.get("response") or fx.get("results") or []

    if not items:
        return {"fixture_id": None, "candidates": [], "picked_reason": "No fixtures found for date."}

    want_home = _norm(home or "")
    want_away = _norm(away or "")

    scored: List[Dict[str, Any]] = []
    for g in items:
        fid, dt, hname, aname = _extract_game_fields(league, g)
        if not fid:
            continue
        h_norm, a_norm = _norm(hname), _norm(aname)

        # basic scoring: +1 if contains, +2 if exact
        score = 0.0
        if want_home:
            if want_home == h_norm:
                score += 2
            elif want_home and want_home in h_norm:
                score += 1
        if want_away:
            if want_away == a_norm:
                score += 2
            elif want_away and want_away in a_norm:
                score += 1

        # if only one team provided, still allow a match with lower score
        scored.append({
            "fixture_id": int(fid),
            "date": dt,
            "home": hname,
            "away": aname,
            "score": score
        })

    # Sort best-first
    scored.sort(key=lambda r: r["score"], reverse=True)

    if not scored:
        return {"fixture_id": None, "candidates": [], "picked_reason": "No parsable fixtures."}

    best = scored[0]
    # heuristic: require some confidence if both teams supplied
    if want_home and want_away:
        if best["score"] >= 3:  # at least one exact + one contains, or both contains
            return {"fixture_id": best["fixture_id"], "candidates": scored[:5], "picked_reason": "High-confidence team match."}
        else:
            return {"fixture_id": None, "candidates": scored[:5], "picked_reason": "Low confidence; confirm selection."}
    else:
        # if only one team was given, pick top but mark as low-confidence if score < 1
        if best["score"] >= 1:
            return {"fixture_id": best["fixture_id"], "candidates": scored[:5], "picked_reason": "Single-team match."}
        return {"fixture_id": None, "candidates": scored[:5], "picked_reason": "Not enough info; confirm selection."}
