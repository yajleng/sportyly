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

# --------- helpers ---------
_LEAGUE_ALIASES = {
    "ncaaf": "ncaaf",
    "cfb": "ncaaf",
    "ncaafootball": "ncaaf",
    "college_football": "ncaaf",
    "ncaaF": "ncaaf",
    "NCaaF": "ncaaf",
    "CFB": "ncaaf",
    "NcAaF": "ncaaf",
    "nfl": "nfl",
    "nba": "nba",
    "ncaab": "ncaab",
    "cbb": "ncaab",
    "soccer": "soccer",
}

def _normalize_league(league_str: str) -> League:
    key = (league_str or "").strip()
    # fast path if already correct lowercase value
    if key in ("nba", "nfl", "ncaaf", "ncaab", "soccer"):
        return key  # type: ignore[return-value]
    # try alias map (case-insensitive)
    mapped = _LEAGUE_ALIASES.get(key) or _LEAGUE_ALIASES.get(key.lower())
    if mapped in ("nba", "nfl", "ncaaf", "ncaab", "soccer"):
        return mapped  # type: ignore[return-value]
    # final guardrail: show the accepted list
    raise HTTPException(
        status_code=422,
        detail="Input should be one of: 'nba', 'nfl', 'ncaaf', 'ncaab', 'soccer'.",
    )

def _client() -> ApiSportsClient:
    settings = get_settings()
    return ApiSportsClient(api_key=settings.apisports_key)

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

# ---------------- Slate (daily fixtures, tz-aware) ----------------
@router.get(
    "/slate",
    summary="Get daily slate (fixtures) for a league",
    description=(
        "Returns the day's fixtures with normalized fields. "
        "Use tz (IANA) to define the calendar day window; defaults to America/New_York. "
        "For soccer, you may pass league_id_override (competition) and season."
    ),
)
def slate(
    league: str,
    date: Optional[str] = Query(None, description="YYYY-MM-DD (defaults to today)"),
    tz: str = Query("America/New_York", description="IANA timezone for calendar-day bucketing"),
    season: Optional[int] = Query(None, description="Season (soccer optional, NCAA often needed)"),
    league_id_override: Optional[int] = Query(None, description="Soccer competition ID (e.g., EPL=39)"),
):
    norm_league: League = _normalize_league(league)
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    qdate = date or _date.today().isoformat()

    c = _client()
    try:
        fx = c.fixtures_by_date(
            league=norm_league,
            date=qdate,
            season=season,
            league_id=league_id_override,
            timezone=tz,  # let provider do local-day bucketing
        )
        items = fx.get("response") or fx.get("results") or []
        rows = [_extract_game_row(norm_league, g) for g in items]
        rows = [r for r in rows if r.get("fixture_id") is not None]
        return {"count": len(rows), "league": norm_league, "date": qdate, "items": rows}
    finally:
        c.close()

# ---------------- Injuries (unified across sports) ----------------
@router.get("/injuries", summary="Unified injuries")
def injuries(
    league: str = Query(..., description="nba | nfl | ncaaf | ncaab | soccer (aliases like cfb accepted)"),
    season: Optional[int] = Query(None, description="Required for soccer; ignored by NFL/NCAAF", example=2025),
    league_id_override: Optional[int] = Query(
        None, description="Soccer competition ID (e.g., EPL=39, LaLiga=140, MLS=253)", example=39
    ),
    team: Optional[int] = Query(None, description="Team ID (required for NFL/NCAAF if player not given)", example=15),
    player: Optional[int] = Query(None, description="Player ID (required for NFL/NCAAF if team not given)", example=53),
):
    norm_league: League = _normalize_league(league)
    if norm_league in ("nba", "ncaab"):
        raise HTTPException(status_code=501, detail="Injuries are not provided for NBA/NCAAB by API-SPORTS.")
    if norm_league in ("nfl", "ncaaf") and not (team or player):
        raise HTTPException(status_code=422, detail="NFL/NCAAF injuries require at least one of: team or player.")
    if norm_league == "soccer" and not (league_id_override and season):
        raise HTTPException(status_code=422, detail="Soccer injuries require league_id_override and season.")

    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    c = _client()
    try:
        kwargs: dict = {}
        if team is not None: kwargs["team"] = team
        if player is not None: kwargs["player"] = player

        if norm_league == "soccer":
            return c.injuries(norm_league, league_id=league_id_override, season=season, **kwargs)
        return c.injuries(norm_league, **kwargs)
    finally:
        c.close()

# ---------------- Resolve id by teams/date ----------------
@router.get("/resolve", summary="Resolve a fixture/game id by teams and date")
def resolve_endpoint(
    league: str,
    date: str,
    home: Optional[str] = None,
    away: Optional[str] = None,
    league_id_override: Optional[int] = None,
    season: Optional[int] = None,
):
    norm_league: League = _normalize_league(league)
    c = _client()
    try:
        return resolve_fixture_id(
            c, league=norm_league, date=date, home=home, away=away,
            league_id_override=league_id_override, season=season,
        )
    finally:
        c.close()

# ---------------- History (with optional odds) ----------------
@router.get("/history")
def history(
    league: str,
    start_date: str,
    end_date: str,
    season: Optional[int] = None,
    include_odds: bool = False,
    league_id_override: Optional[int] = None,
    bookmaker_id: Optional[int] = Query(None, description="Prefer odds from this bookmaker id"),
    max_odds_lookups: int = 200,
):
    norm_league: League = _normalize_league(league)
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    c = _client()
    try:
        fx = c.fixtures_range(
            norm_league,
            from_date=start_date,
            to_date=end_date,
            season=season,
            league_id=league_id_override,
        )
        items = fx.get("response") or fx.get("results") or []

        out: List[dict] = []
        lookups = 0

        for g in items:
            if norm_league == "soccer":
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
                    odds_raw = c.odds_for_fixture(norm_league, int(fid))
                    row["odds"] = normalize_odds(odds_raw, preferred_bookmaker_id=bookmaker_id)
                    lookups += 1
                except Exception:
                    row["odds"] = None

            out.append(row)

        return {"count": len(out), "league": norm_league, "range": [start_date, end_date], "items": out}
    finally:
        c.close()

# ---------------- Odds (auto-resolve supported) ----------------
@router.get(
    "/odds",
    summary="Fixture/game odds (raw or normalized)",
    description="Pass a fixture_id or (date + home/away) and I will resolve first.",
)
def odds(
    league: str,
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
    norm_league: League = _normalize_league(league)
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    c = _client()
    try:
        resolved_reason = None
        if fixture_id is None:
            if not date or not (home or away):
                raise HTTPException(status_code=422, detail="Provide fixture_id OR (date and at least one of home/away).")
            res = resolve_fixture_id(
                c, league=norm_league, date=date, home=home, away=away,
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

        payload = c.odds_for_fixture(norm_league, int(fixture_id), **extra)
        return payload if raw else {
            "fixture_id": fixture_id,
            "resolved": resolved_reason,
            "odds": normalize_odds(payload, preferred_bookmaker_id=bookmaker_id),
        }
    finally:
        c.close()
