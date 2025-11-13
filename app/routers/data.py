# app/routers/data.py
from __future__ import annotations

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from datetime import date as _date

from ..clients.apisports import ApiSportsClient, League
from ..core.config import get_settings
from ..services.odds import normalize_odds
from ..services.resolve import resolve_fixture_id

router = APIRouter(prefix="/data", tags=["data"])


def _client() -> ApiSportsClient:
    settings = get_settings()
    return ApiSportsClient(api_key=settings.apisports_key)

# ---------- helpers ----------
def _extract_game_row(league: League, g: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize minimal game fields across sports."""
    if league == "soccer":
        fid = g["fixture"]["id"]
        dt = g["fixture"]["date"]
        home = g["teams"]["home"]["name"]
        away = g["teams"]["away"]["name"]
        venue_city = ((g.get("fixture") or {}).get("venue") or {}).get("city")
        return {
            "fixture_id": int(fid),
            "date": dt,
            "home": home,
            "away": away,
            "venue_city": venue_city,
        }
    else:
        fid = g.get("id") or g.get("game", {}).get("id") or g.get("fixture", {}).get("id")
        dt = g.get("date") or g.get("game", {}).get("date")
        teams = g.get("teams") or {}
        home = (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name")
        away = (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name")
        venue_city = ((g.get("venue") or {}) or (g.get("game") or {}).get("venue") or {}).get("city")
        return {
            "fixture_id": int(fid) if fid else None,
            "date": dt,
            "home": home,
            "away": away,
            "venue_city": venue_city,
        }

# ---------------- Slate (daily fixtures) ----------------
@router.get(
    "/slate",
    summary="Get daily slate (fixtures) for a league",
    description=(
        "Returns the day's fixtures with normalized fields. "
        "For soccer, you may pass league_id_override (competition) and season."
    ),
)
def slate(
    league: League,
    date: Optional[str] = Query(None, description="YYYY-MM-DD (defaults to today)"),
    season: Optional[int] = Query(None, description="Season (soccer optional, others ignored)"),
    league_id_override: Optional[int] = Query(None, description="Soccer competition ID (e.g., EPL=39)"),
):
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    qdate = date or _date.today().isoformat()

    client = _client()
    try:
        fx = client.fixtures_by_date(
            league=league,
            date=qdate,
            season=season,
            league_id=league_id_override,
        )
        items = fx.get("response") or fx.get("results") or []
        rows = [_extract_game_row(league, g) for g in items]
        # filter any without id just in case
        rows = [r for r in rows if r.get("fixture_id") is not None]
        return {"count": len(rows), "league": league, "date": qdate, "items": rows}
    finally:
        client.close()

# ---------------- Injuries (unified across sports) ----------------
@router.get(
    "/injuries",
    summary="Unified injuries",
    description=(
        "Get current injuries from API-SPORTS.\n\n"
        "**Rules by league:**\n"
        "- **nfl / ncaaf** (american-football): **team OR player is required** (at least one).\n"
        "- **soccer** (API-Football v3): **league_id_override** (competition) **AND** **season** are required; team/player optional.\n"
        "- **nba / ncaab**: injuries not provided by API-SPORTS → 501.\n\n"
        "**Examples:**\n"
        "- NFL by team: `/data/injuries?league=nfl&team=15`\n"
        "- NFL by player: `/data/injuries?league=nfl&player=53`\n"
        "- Soccer (EPL): `/data/injuries?league=soccer&league_id_override=39&season=2025`\n"
        "- NBA (not supported): `/data/injuries?league=nba`\n"
    ),
)
def injuries(
    league: League = Query(..., description="nba | nfl | ncaaf | ncaab | soccer"),
    season: Optional[int] = Query(None, description="Required for soccer; ignored by NFL/NCAAF", example=2025),
    league_id_override: Optional[int] = Query(
        None, description="Soccer competition ID (e.g., EPL=39, LaLiga=140, MLS=253)", example=39
    ),
    team: Optional[int] = Query(None, description="Team ID (required for NFL/NCAAF if player not given)", example=15),
    player: Optional[int] = Query(None, description="Player ID (required for NFL/NCAAF if team not given)", example=53),
):
    if league in ("nba", "ncaab"):
        raise HTTPException(status_code=501, detail="Injuries are not provided for NBA/NCAAB by API-SPORTS.")
    if league in ("nfl", "ncaaf") and not (team or player):
        raise HTTPException(status_code=422, detail="NFL/NCAAF injuries require at least one of: team or player.")
    if league == "soccer" and not (league_id_override and season):
        raise HTTPException(status_code=422, detail="Soccer injuries require league_id_override (competition) and season.")

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
            return client.injuries(league, league_id=league_id_override, season=season, **kwargs)
        return client.injuries(league, **kwargs)
    finally:
        client.close()

# ---------------- Resolve id by teams/date ----------------
@router.get("/resolve", summary="Resolve a fixture/game id by teams and date")
def resolve_endpoint(
    league: League,
    date: str,
    home: Optional[str] = None,
    away: Optional[str] = None,
    league_id_override: Optional[int] = None,
    season: Optional[int] = None,
):
    client = _client()
    try:
        return resolve_fixture_id(
            client,
            league=league,
            date=date,
            home=home,
            away=away,
            league_id_override=league_id_override,
            season=season,
        )
    finally:
        client.close()

# ---------------- History (with optional odds) ----------------
@router.get("/history")
def history(
    league: League,
    start_date: str,
    end_date: str,
    season: Optional[int] = None,
    include_odds: bool = False,
    league_id_override: Optional[int] = None,
    bookmaker_id: Optional[int] = Query(None, description="Prefer odds from this bookmaker id"),
    max_odds_lookups: int = 200,
):
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
                hsc = sc.get("home"); asc = sc.get("away")
                hs = (hsc.get("total") if isinstance(hsc, dict) else hsc)
                as_ = (asc.get("total") if isinstance(asc, dict) else asc)

            row = {"fixture_id": fid, "date": dt, "home": home, "away": away, "home_score": hs, "away_score": as_}

            if include_odds and lookups < max_odds_lookups and fid:
                try:
                    odds_raw = client.odds_for_fixture(league, int(fid))
                    row["odds"] = normalize_odds(odds_raw, preferred_bookmaker_id=bookmaker_id)
                    lookups += 1
                except Exception:
                    row["odds"] = None

            out.append(row)

        return {"count": len(out), "league": league, "range": [start_date, end_date], "items": out}
    finally:
        client.close()

# ---------------- Odds (auto-resolve supported) ----------------
@router.get(
    "/odds",
    summary="Fixture/game odds (raw or normalized)",
    description=(
        "Pass a `fixture_id` (soccer fixture / AF game id) **or** give `date + home + away` and I will resolve the id first."
    ),
)
def odds(
    league: League,
    fixture_id: Optional[int] = Query(None, description="Soccer fixture id or American-football game id"),
    raw: bool = False,
    bookmaker_id: Optional[int] = Query(None, description="Prefer odds from this bookmaker id"),
    bet_id: Optional[int] = Query(None, description="Filter to a specific bet/market id"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD (use with home/away if fixture_id not given)"),
    home: Optional[str] = None,
    away: Optional[str] = None,
    league_id_override: Optional[int] = None,
    season: Optional[int] = None,
):
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    client = _client()
    try:
        resolved_reason = None
        if fixture_id is None:
            if not date or not (home or away):
                raise HTTPException(status_code=422, detail="Provide fixture_id OR (date and at least one of home/away).")
            res = resolve_fixture_id(
                client, league=league, date=date, home=home, away=away,
                league_id_override=league_id_override, season=season
            )
            fixture_id = res.get("fixture_id")
            resolved_reason = res.get("picked_reason")
            if not fixture_id:
                raise HTTPException(status_code=409, detail={
                    "message": "Could not confidently resolve fixture; please confirm one of the candidates.",
                    "candidates": res.get("candidates", []),
                })

        extra: dict = {}
        if bookmaker_id is not None: extra["bookmaker"] = bookmaker_id
        if bet_id is not None: extra["bet"] = bet_id

        payload = client.odds_for_fixture(league, int(fixture_id), **extra)
        return payload if raw else {
            "fixture_id": fixture_id,
            "resolved": resolved_reason,
            "odds": normalize_odds(payload, preferred_bookmaker_id=bookmaker_id),
        }
    finally:
        client.close()
