# app/routers/data.py
from __future__ import annotations

from typing import List, Optional, Dict, Any, Literal
from datetime import date as _date

from fastapi import APIRouter, Query, HTTPException, Depends

from ..clients.apisports import ApiSportsClient
from ..core.config import get_settings
from ..services.odds import normalize_odds
from ..services.resolve import resolve_fixture_id
from ..services.validation import validate_league
from ..services.markets import resolve_bet_id
from ..schemas.query import SlateQuery, ResolveQuery, OddsQuery
from ..services.cache import cache  # small in-proc TTL cache
# Optional derived metric (endpoint guarded by import’s existence)
try:
    from ..services.ratings import compute_efficiency
except Exception:  # pragma: no cover
    compute_efficiency = None  # type: ignore[assignment]

router = APIRouter(prefix="/data", tags=["data"])

# Local League literal to avoid import cycles
League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]


# ---------- client/key helpers ----------
def _client() -> ApiSportsClient:
    settings = get_settings()
    return ApiSportsClient(api_key=settings.apisports_key)

def _ensure_key():
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")


# ---------- shape helpers ----------
def _extract_game_row(league: League, g: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize minimal game fields across families."""
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


def _auto_resolve_or_id(
    client: ApiSportsClient,
    league: League,
    fixture_id: Optional[int],
    *,
    date: Optional[str],
    home: Optional[str],
    away: Optional[str],
    league_id_override: Optional[int],
    season: Optional[int],
) -> Dict[str, Any]:
    """
    Returns dict with:
      fixture_id, resolved (reason or None), candidates (if not resolvable)
    """
    if fixture_id is not None:
        return {"fixture_id": int(fixture_id), "resolved": None, "candidates": []}

    if not date or not (home or away):
        raise HTTPException(
            status_code=422,
            detail="Provide fixture_id OR (date and at least one of home/away).",
        )

    res = resolve_fixture_id(
        client,
        league=league,
        date=date,
        home=home,
        away=away,
        league_id_override=league_id_override,
        season=season,
    )
    fid = res.get("fixture_id")
    if not fid:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Could not confidently resolve fixture; please confirm one of the candidates.",
                "candidates": res.get("candidates", []),
            },
        )
    return {"fixture_id": int(fid), "resolved": res.get("picked_reason"), "candidates": []}


# ---------------- Bookmakers ----------------
@router.get(
    "/bookmakers",
    summary="List bookmaker IDs for a league",
    description="Returns the API-SPORTS bookmaker catalog (id, name) for the selected league.",
)
def bookmakers(league: League = Query(..., description="nba | nfl | ncaaf | ncaab | soccer")):
    validate_league(league)
    _ensure_key()

    key = ("bookmakers", league)
    cached = cache.get(key)
    if cached is not None:
        return cached

    c = _client()
    try:
        payload = c.bookmakers(league)
        rows = payload.get("response") or payload.get("bookmakers") or []
        out = [{"id": int(b.get("id")), "name": b.get("name")} for b in rows if b.get("id")]
        out.sort(key=lambda x: (x["name"] or "").lower())
        result = {"count": len(out), "league": league, "items": out}
        cache.set(key, result)
        return result
    finally:
        c.close()


# ---------------- Slate (daily fixtures) ----------------
@router.get(
    "/slate",
    summary="Get daily slate (fixtures) for a league",
    description="Returns the day's fixtures with normalized fields.",
)
def slate(
    q: SlateQuery = Depends(),
    timezone: Optional[str] = Query(None, description="e.g., UTC, America/New_York"),
    page: Optional[int] = Query(None, ge=1, description="Provider paging"),
):
    _ensure_key()
    qdate = q.date or _date.today().isoformat()

    key = ("slate", q.league, qdate, q.season, q.league_id_override, timezone, page)
    cached = cache.get(key)
    if cached is not None:
        return cached

    client = _client()
    try:
        fx = client.fixtures_by_date(
            league=q.league,
            date=qdate,
            season=q.season,
            league_id=q.league_id_override,
            timezone=timezone,
            page=page,
        )
        items = fx.get("response") or fx.get("results") or []
        rows = [_extract_game_row(q.league, g) for g in items]
        rows = [r for r in rows if r.get("fixture_id") is not None]
        result = {"count": len(rows), "league": q.league, "date": qdate, "items": rows}
        cache.set(key, result)
        return result
    finally:
        client.close()


# ---------------- Injuries (unified across sports) ----------------
@router.get(
    "/injuries",
    summary="Unified injuries",
    description=(
        "Get current injuries from API-SPORTS.\n\n"
        "Rules:\n"
        "- nfl/ncaaf: team OR player required\n"
        "- soccer: league_id_override AND season required\n"
        "- nba/ncaab: not provided by API-SPORTS"
    ),
)
def injuries(
    league: League = Query(..., description="nba | nfl | ncaaf | ncaab | soccer"),
    season: Optional[int] = Query(None, description="Required for soccer; ignored by NFL/NCAAF", example=2025),
    league_id_override: Optional[int] = Query(None, description="Soccer competition ID", example=39),
    team: Optional[int] = Query(None, description="Team ID (NFL/NCAAF if no player)", example=15),
    player: Optional[int] = Query(None, description="Player ID (NFL/NCAAF if no team)", example=53),
):
    if league in ("nba", "ncaab"):
        raise HTTPException(status_code=501, detail="Injuries are not provided for NBA/NCAAB by API-SPORTS.")
    if league in ("nfl", "ncaaf") and not (team or player):
        raise HTTPException(status_code=422, detail="NFL/NCAAF injuries require at least one of: team or player.")
    if league == "soccer" and not (league_id_override and season):
        raise HTTPException(status_code=422, detail="Soccer injuries require league_id_override and season.")

    _ensure_key()

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
def resolve_endpoint(q: ResolveQuery = Depends()):
    _ensure_key()
    client = _client()
    try:
        return resolve_fixture_id(
            client,
            league=q.league,
            date=q.date,
            home=q.home,
            away=q.away,
            league_id_override=q.league_id_override,
            season=q.season,
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
    timezone: Optional[str] = None,
    page: Optional[int] = None,
):
    _ensure_key()

    client = _client()
    try:
        fx = client.fixtures_range(
            league,
            from_date=start_date,
            to_date=end_date,
            season=season,
            league_id=league_id_override,
            timezone=timezone,
            page=page,
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


# ---------------- Odds (auto-resolve + market/period aliases) ----------------
@router.get(
    "/odds",
    summary="Fixture/game odds (raw or normalized)",
    description="Pass a fixture_id or give date+home/away to auto-resolve. Optionally use market alias and period.",
)
def odds(q: OddsQuery = Depends(), market: Optional[str] = Query(None), period: Optional[str] = Query(None)):
    _ensure_key()

    client = _client()
    try:
        resolved = _auto_resolve_or_id(
            client,
            q.league,
            q.fixture_id,
            date=q.date,
            home=q.home,
            away=q.away,
            league_id_override=q.league_id_override,
            season=q.season,
        )
        fixture_id = resolved["fixture_id"]
        resolved_reason = resolved["resolved"]

        # Friendly alias -> bet id
        bet_id = q.bet_id
        if bet_id is None and market:
            bet_id = resolve_bet_id(q.league, market, period)

        extra: dict = {}
        if q.bookmaker_id is not None:
            extra["bookmaker"] = q.bookmaker_id
        if bet_id is not None:
            extra["bet"] = bet_id

        payload = client.odds_for_fixture(q.league, int(fixture_id), **extra)
        if q.raw:
            return payload

        return {
            "fixture_id": fixture_id,
            "resolved": resolved_reason,
            "odds": normalize_odds(payload, preferred_bookmaker_id=q.bookmaker_id),
        }
    finally:
        client.close()


# ---------------- Props (auto-resolve; requires market alias) ----------------
@router.get(
    "/props",
    summary="Player props odds (auto-resolve fixture)",
    description="Provide fixture_id or (date + home/away). Use a player prop market alias (e.g., player_points).",
)
def props(
    league: League = Query(...),
    market: str = Query(..., description="player prop alias, e.g., player_points, rush_yards"),
    period: Optional[str] = Query(None),
    fixture_id: Optional[int] = Query(None),
    date: Optional[str] = Query(None),
    home: Optional[str] = Query(None),
    away: Optional[str] = Query(None),
    bookmaker_id: Optional[int] = Query(None),
    season: Optional[int] = Query(None),
    league_id_override: Optional[int] = Query(None),
    raw: bool = Query(False),
):
    validate_league(league)
    _ensure_key()

    client = _client()
    try:
        resolved = _auto_resolve_or_id(
            client,
            league,
            fixture_id,
            date=date,
            home=home,
            away=away,
            league_id_override=league_id_override,
            season=season,
        )
        fid = resolved["fixture_id"]

        bet_id = resolve_bet_id(league, market, period)
        if bet_id is None:
            raise HTTPException(status_code=422, detail=f"Unknown market alias '{market}' for league '{league}'.")

        payload = client.odds_for_fixture(league, fid, bookmaker=bookmaker_id, bet=bet_id)
        if raw:
            return payload

        return {
            "fixture_id": fid,
            "resolved": resolved["resolved"],
            "odds": normalize_odds(payload, preferred_bookmaker_id=bookmaker_id),
        }
    finally:
        client.close()


# ---------------- Stats: game team boxscore (auto-resolve) ----------------
@router.get(
    "/stats/game/teams",
    summary="Team stats for a single game (auto-resolve id)",
    description="For nfl/ncaaf/nba/ncaab supply game_id OR date+home+away. Soccer uses fixtures/statistics.",
)
def stats_game_teams(
    league: League = Query(..., description="nfl | ncaaf | nba | ncaab | soccer"),
    game_id: Optional[int] = Query(None, description="Game/fixture id"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD (used for resolve)"),
    home: Optional[str] = Query(None, description="Home team name (resolve aid)"),
    away: Optional[str] = Query(None, description="Away team name (resolve aid)"),
    league_id_override: Optional[int] = None,
    season: Optional[int] = None,
):
    validate_league(league)
    _ensure_key()

    client = _client()
    try:
        resolved = _auto_resolve_or_id(
            client,
            league,
            game_id,
            date=date,
            home=home,
            away=away,
            league_id_override=league_id_override,
            season=season,
        )
        gid = resolved["fixture_id"]
        data = client.game_team_stats(league, int(gid))
        return {"fixture_id": gid, "resolved": resolved["resolved"], "data": data}
    finally:
        client.close()


# ---------------- Stats: game player boxscore (auto-resolve) ----------------
@router.get(
    "/stats/game/players",
    summary="Player stats for a single game (auto-resolve id)",
    description="For nfl/ncaaf/nba/ncaab/soccer supply game_id OR date+home+away.",
)
def stats_game_players(
    league: League = Query(..., description="nfl | ncaaf | nba | ncaab | soccer"),
    game_id: Optional[int] = Query(None),
    date: Optional[str] = Query(None),
    home: Optional[str] = Query(None),
    away: Optional[str] = Query(None),
    league_id_override: Optional[int] = None,
    season: Optional[int] = None,
):
    validate_league(league)
    _ensure_key()

    client = _client()
    try:
        resolved = _auto_resolve_or_id(
            client,
            league,
            game_id,
            date=date,
            home=home,
            away=away,
            league_id_override=league_id_override,
            season=season,
        )
        gid = resolved["fixture_id"]
        data = client.game_player_stats(league, int(gid))
        return {"fixture_id": gid, "resolved": resolved["resolved"], "data": data}
    finally:
        client.close()


# ---------------- Stats: soccer team season ----------------
@router.get(
    "/stats/soccer/team",
    summary="Soccer season team statistics (v3)",
    description="GET /teams/statistics?team=&league=&season=",
)
def stats_soccer_team(
    team_id: int = Query(...),
    league_id: int = Query(...),
    season: int = Query(...),
):
    _ensure_key()
    client = _client()
    try:
        return client.soccer_team_season_stats(team_id=team_id, league_id=league_id, season=season)
    finally:
        client.close()


# ---------------- Windowed stats (batch helpers for features) ----------------
@router.get(
    "/stats/window/teams",
    summary="Windowed per-game team statistics (v1 families only)",
    description="Collect per-game team stats for multiple games by ids (dash-separated).",
)
def stats_window_teams(
    league: League = Query(..., description="nfl | ncaaf | nba | ncaab"),
    game_ids: Optional[str] = Query(None, description='Dash-separated ids, e.g. "123-456-789"'),
):
    validate_league(league)
    if league == "soccer":
        raise HTTPException(status_code=422, detail="Use /stats/soccer/team for soccer contexts.")
    _ensure_key()

    if not game_ids:
        raise HTTPException(status_code=422, detail="Provide game_ids (dash-separated).")

    ids = [int(x) for x in game_ids.split("-") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=422, detail="No valid ids in game_ids.")

    client = _client()
    try:
        data = client.game_team_stats_batch(league, ids)
        return {"league": league, "count": len(ids), "ids": ids, "data": data}
    finally:
        client.close()


@router.get(
    "/stats/window/players",
    summary="Windowed per-game player statistics (v1 families only)",
    description="Collect per-game player stats for multiple games by ids (dash-separated).",
)
def stats_window_players(
    league: League = Query(..., description="nfl | ncaaf | nba | ncaab"),
    game_ids: Optional[str] = Query(None, description='Dash-separated ids, e.g. "123-456-789"'),
):
    validate_league(league)
    if league == "soccer":
        raise HTTPException(status_code=422, detail="Use /stats/soccer/team for soccer contexts.")
    _ensure_key()

    if not game_ids:
        raise HTTPException(status_code=422, detail="Provide game_ids (dash-separated).")

    ids = [int(x) for x in game_ids.split("-") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=422, detail="No valid ids in game_ids.")

    client = _client()
    try:
        data = client.game_player_stats_batch(league, ids)
        return {"league": league, "count": len(ids), "ids": ids, "data": data}
    finally:
        client.close()


# ---------------- Derived Ratings (optional) ----------------
@router.get("/ratings", summary="Computed team offensive/defensive ratings")
def ratings(
    league: League = Query(...),
    team_name: str = Query(..., description="Exact team name as appears in API-Sports"),
    start_date: str = Query(...),
    end_date: str = Query(...),
    season: Optional[int] = None,
    league_id_override: Optional[int] = None,
    window: int = Query(10, ge=1, le=40, description="Recent N games to average"),
    timezone: Optional[str] = None,
    page: Optional[int] = None,
):
    if compute_efficiency is None:
        raise HTTPException(status_code=501, detail="ratings service not available in this build.")
    _ensure_key()

    client = _client()
    try:
        fx = client.fixtures_range(
            league=league,
            from_date=start_date,
            to_date=end_date,
            season=season,
            league_id=league_id_override,
            timezone=timezone,
            page=page,
        )
        items = (fx.get("response") or fx.get("results") or [])[-window:]
        return {
            "league": league,
            "team": team_name,
            "window": len(items),
            "ratings": compute_efficiency(items, team_name),  # type: ignore[misc]
        }
    finally:
        client.close()
