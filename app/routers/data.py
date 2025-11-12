# app/routers/data.py
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException

from ..clients.apisports import ApiSportsClient, League
from ..core.config import get_settings
from ..services.odds import normalize_odds

router = APIRouter(prefix="/data", tags=["data"])

def _client() -> ApiSportsClient:
    settings = get_settings()
    return ApiSportsClient(api_key=settings.apisports_key)

# ---------------- Injuries ----------------
@router.get("/injuries")
def injuries(
    league: League = Query(..., description="nba | nfl | ncaaf | ncaab | soccer"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD (optional)"),
    league_id_override: Optional[int] = Query(None, description="Override default league id (mainly for soccer)"),
):
    """
    Fetch injury reports from API-SPORTS. Returns raw provider JSON.
    """
    client = _client()
    try:
        return client.injuries(league, date=date, league_id=league_id_override)
    finally:
        client.close()

# ---------------- History (with optional odds) ----------------
@router.get("/history")
def history(
    league: League,
    start_date: str,                 # YYYY-MM-DD
    end_date: str,                   # YYYY-MM-DD
    season: Optional[int] = None,
    include_odds: bool = False,
    league_id_override: Optional[int] = None,
    max_odds_lookups: int = 200,     # safety to avoid rate limits
):
    """
    Returns fixtures between dates with final scores.
    If include_odds=true, attaches normalized ML/Spread/Total markets (best-effort, first bookmaker).
    """
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    client = ApiSportsClient(api_key=settings.apisports_key)
    try:
        fx = client.fixtures_range(
            league,
            from_date=start_date,
            to_date=end_date,
            season=season,
            league_id=league_id_override,
        )
        items = fx.get("response") or fx.get("results") or []

        out: List[dict] = []
        lookups = 0

        for g in items:
            # Normalize minimal fields across sports
            if league == "soccer":
                fid = g["fixture"]["id"]
                dt = g["fixture"]["date"]
                home = g["teams"]["home"]["name"]
                away = g["teams"]["away"]["name"]
                hs = (g.get("goals") or {}).get("home")
                as_ = (g.get("goals") or {}).get("away")
            else:
                fid = g.get("id") or g.get("game", {}).get("id") or g.get("fixture", {}).get("id")
                dt = g.get("date") or g.get("game", {}).get("date")
                teams = g.get("teams") or {}
                home = (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name")
                away = (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name")
                sc = g.get("scores") or g.get("score") or {}
                # handle dict-or-int shapes
                hsc = sc.get("home")
                asc = sc.get("away")
                hs = (hsc.get("total") if isinstance(hsc, dict) else hsc)
                as_ = (asc.get("total") if isinstance(asc, dict) else asc)

            row = {
                "fixture_id": fid,
                "date": dt,
                "home": home,
                "away": away,
                "home_score": hs,
                "away_score": as_,
            }

            if include_odds and lookups < max_odds_lookups and fid:
                try:
                    odds_raw = client.odds_for_fixture(league, int(fid))
                    row["odds"] = normalize_odds(odds_raw)
                    lookups += 1
                except Exception:
                    row["odds"] = None

            out.append(row)

        return {"count": len(out), "league": league, "range": [start_date, end_date], "items": out}

    finally:
        client.close()
