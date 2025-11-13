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

# ---------------- Injuries (unified across sports) ----------------
@router.get("/injuries")
def injuries(
    league: League = Query(..., description="nba | nfl | ncaaf | ncaab | soccer"),
    # optional, varies by sport:
    season: Optional[int] = Query(None, description="Required for soccer; ignored by NFL/NCAAF"),
    league_id_override: Optional[int] = Query(None, description="Soccer competition ID (e.g., EPL=39)"),
    team: Optional[int] = Query(None, description="Team ID (required for NFL/NCAAF if player not given)"),
    player: Optional[int] = Query(None, description="Player ID (required for NFL/NCAAF if team not given)"),
):
    """
    Unified injuries gateway:

    - NFL/NCAAF (american-football): requires at least one of team or player.
    - Soccer (football v3): requires league_id_override and season; team/player optional.
    - NBA/NCAAB: not available in API-SPORTS -> 501 Not Implemented.
    """
    # Validate per-league requirements
    if league in ("nba", "ncaab"):
        raise HTTPException(status_code=501, detail="Injuries not available for basketball in API-SPORTS")

    if league in ("nfl", "ncaaf"):
        if not team and not player:
            raise HTTPException(status_code=422, detail="Provide team or player for NFL/NCAAF injuries")

    if league == "soccer":
        if not league_id_override or not season:
            raise HTTPException(status_code=422, detail="Provide league_id_override and season for soccer injuries")

    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    client = _client()
    try:
        kwargs: dict = {}
        if team is not None:
            kwargs["team"] = team
        if player is not None:
            kwargs["player"] = player

        if league == "soccer":
            # soccer needs league + season (client maps league_id -> "league" query)
            return client.injuries(league, league_id=league_id_override, season=season, **kwargs)

        # american-football: just pass team/player (no season needed)
        return client.injuries(league, **kwargs)
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

    client = _client()
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

# ---------------- Odds (raw or normalized) ----------------
@router.get("/odds")
def odds(
    league: League,
    fixture_id: int,
    raw: bool = False,
):
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")
    client = _client()
    try:
        payload = client.odds_for_fixture(league, fixture_id)
        return payload if raw else {"fixture_id": fixture_id, "odds": normalize_odds(payload)}
    finally:
        client.close()
