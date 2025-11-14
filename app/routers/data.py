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

# ---------- league normalization (case-insensitive + aliases) ----------
_LEAGUE_ALIASES = {
    "nba": "nba",
    "nfl": "nfl",
    "ncaaf": "ncaaf",
    "ncaab": "ncaab",
    "soccer": "soccer",
    # helpful aliases
    "ncaa": "ncaaf",
    "cfb": "ncaaf",
    "college": "ncaaf",
}

def _parse_league(value: str) -> League:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="league must be a string.")
    norm = _LEAGUE_ALIASES.get(value.strip().lower())
    if not norm:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid league.",
                "received": value,
                "allowed": list(_LEAGUE_ALIASES.keys()),
                "tip": "league is case-insensitive (e.g., ncaaf, NFL, CFB are OK).",
            },
        )
    # return as the typed alias expected by clients
    return norm  # type: ignore[return-value]

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
    summary="Get daily slate (fixtures) for a league (case-insensitive league)",
    description=(
        "Returns the day's fixtures with normalized fields. "
        "For soccer, you may pass league_id_override (competition) and season. "
        "league is case-insensitive (e.g., NFL, ncaaf, CFB)."
    ),
)
def slate(
    league: str,
    date: Optional[str] = Query(None, description="YYYY-MM-DD (defaults to today)"),
    season: Optional[int] = Query(None, description="Season (soccer optional, others ignored)"),
    league_id_override: Optional[int] = Query(None, description="Soccer competition ID (e.g., EPL=39)"),
):
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    league_norm: League = _parse_league(league)
    qdate = date or _date.today().isoformat()

    client = _client()
    try:
        fx = client.fixtures_by_date(
            league=league_norm,
            date=qdate,
            season=season,
            league_id=league_id_override,
        )
        items = fx.get("response") or fx.get("results") or []
        rows = [_extract_game_row(league_norm, g) for g in items]
        rows = [r for r in rows if r.get("fixture_id") is not None]
        return {"count": len(rows), "league": league_norm, "date": qdate, "items": rows}
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
        "- **nba / ncaab**: injuries not provided by API-SPORTS.\n\n"
        "league is case-insensitive."
    ),
)
def injuries(
    league: str = Query(..., description="nba | nfl | ncaaf | ncaab | soccer (case-insensitive)"),
    season: Optional[int] = Query(None, description="Required for soccer; ignored by NFL/NCAAF", example=2025),
    league_id_override: Optional[int] = Query(
        None, description="Soccer competition ID (e.g., EPL=39, LaLiga=140, MLS=253)", example=39
    ),
    team: Optional[int] = Query(None, description="Team ID (required for NFL/NCAAF if player not given)", example=15),
    player: Optional[int] = Query(None, description="Player ID (required for NFL/NCAAF if team not given)", example=53),
):
    league_norm: League = _parse_league(league)

    if league_norm in ("nba", "ncaab"):
        raise HTTPException(status_code=501, detail="Injuries are not provided for NBA/NCAAB by API-SPORTS.")
    if league_norm in ("nfl", "ncaaf") and not (team or player):
        raise HTTPException(status_code=422, detail="NFL/NCAAF injuries require at least one of: team or player.")
    if league_norm == "soccer" and not (league_id_override and season):
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

        if league_norm == "soccer":
            return client.injuries(league_norm, league_id=league_id_override, season=season, **kwargs)
        return client.injuries(league_norm, **kwargs)
    finally:
        client.close()

# ---------------- Resolve id by teams/date ----------------
@router.get("/resolve", summary="Resolve a fixture/game id by teams and date (case-insensitive league)")
def resolve_endpoint(
    league: str,
    date: str,
    home: Optional[str] = None,
    away: Optional[str] = None,
    league_id_override: Optional[int] = None,
    season: Optional[int] = None,
):
    league_norm: League = _parse_league(league)
    client = _client()
    try:
        return resolve_fixture_id(
            client,
            league=league_norm,
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
    league: str,
    start_date: str,
    end_date: str,
    season: Optional[int] = None,
    include_odds: bool = False,
    league_id_override: Optional[int] = None,
    bookmaker_id: Optional[int] = Query(None, description="Prefer odds from this bookmaker id"),
    max_odds_lookups: int = 200,
):
    league_norm: League = _parse_league(league)

    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    client = _client()
    try:
        fx = client.fixtures_range(
            league=league_norm,
            from_date=start_date,
            to_date=end_date,
            season=season,
            league_id=league_id_override,
        )
        items = fx.get("response") or fx.get("results") or []

        out: List[dict] = []
        lookups = 0

        for g in items:
            if league_norm == "soccer":
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
                    odds_raw = client.odds_for_fixture(league_norm, int(fid))
                    row["odds"] = normalize_odds(odds_raw, preferred_bookmaker_id=bookmaker_id)
                    lookups += 1
                except Exception:
                    row["odds"] = None

            out.append(row)

        return {"count": len(out), "league": league_norm, "range": [start_date, end_date], "items": out}
    finally:
        client.close()

# ---------------- Odds (auto-resolve supported) ----------------
@router.get(
    "/odds",
    summary="Fixture/game odds (raw or normalized) — case-insensitive league",
    description=(
        "Pass a `fixture_id` (soccer fixture / AF game id) **or** give `date + home + away` and I will resolve the id first."
    ),
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
    league_norm: League = _parse_league(league)

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
                client, league=league_norm, date=date, home=home, away=away,
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

        payload = client.odds_for_fixture(league_norm, int(fixture_id), **extra)
        return payload if raw else {
            "fixture_id": fixture_id,
            "resolved": resolved_reason,
            "odds": normalize_odds(payload, preferred_bookmaker_id=bookmaker_id),
        }
    finally:
        client.close()
