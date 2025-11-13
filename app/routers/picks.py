# app/routers/picks.py
from __future__ import annotations

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query

from ..clients.apisports import ApiSportsClient, League
from ..core.config import get_settings
from ..services.odds import normalize_odds

# optional picker (value/edge). If missing, we still return odds.
_HAS_PICKER = True
try:
    from ..services.picks import compute_picks_from_normalized as _compute_picks  # type: ignore
except Exception:
    _HAS_PICKER = False
    _compute_picks = None  # type: ignore

router = APIRouter(tags=["picks"])


def _client() -> ApiSportsClient:
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")
    return ApiSportsClient(api_key=settings.apisports_key)

# -------- /picks/auto : run across the daily slate --------
@router.get(
    "/picks/auto",
    summary="Auto picks for a date (slate → odds → normalize → picks)",
    description=(
        "Batch pipeline for a given date. Uses /data/slate to discover games, "
        "then fetches odds and computes picks. Start with NCAAF for best coverage."
    ),
)
def picks_auto(
    league: League = Query(..., description="ncaaf|nfl|nba|ncaab|soccer"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD (defaults to today)"),
    season: Optional[int] = Query(None, description="Season (soccer optional)"),
    league_id_override: Optional[int] = Query(None, description="Soccer competition (e.g., EPL=39)"),
    bookmaker_id: Optional[int] = Query(None, description="Prefer odds from this bookmaker id"),
    ev_threshold: float = Query(0.02, ge=0.0, le=0.25, description="Min EV/edge to keep a pick (default 2%)"),
    max_games: int = Query(50, ge=1, description="Safety cap for slate size"),
    raw_odds: bool = Query(False, description="Return provider odds instead of normalized"),
):
    """
    1) Get slate for the date
    2) For each game: get odds -> normalize -> compute picks (if picker present)
    3) Return ranked picks per game
    """
    settings = get_settings()
    if not settings.apisports_key:
        raise HTTPException(status_code=500, detail="APISPORTS_KEY missing")

    qdate = date  # let /data/slate default to today when None

    client = _client()
    try:
        # ---- 1) slate ----
        slate_payload = client.fixtures_by_date(
            league=league, date=(qdate or ""), season=season, league_id=league_id_override
        )
        items = slate_payload.get("response") or slate_payload.get("results") or []
        games: List[Dict[str, Any]] = []

        # normalize minimal fields
        if league == "soccer":
            for g in items[:max_games]:
                try:
                    games.append({
                        "fixture_id": int(g["fixture"]["id"]),
                        "date": g["fixture"]["date"],
                        "home": g["teams"]["home"]["name"],
                        "away": g["teams"]["away"]["name"],
                    })
                except Exception:
                    continue
        else:
            for g in items[:max_games]:
                fid = g.get("id") or g.get("game", {}).get("id") or g.get("fixture", {}).get("id")
                if not fid:
                    continue
                teams = g.get("teams") or {}
                games.append({
                    "fixture_id": int(fid),
                    "date": g.get("date") or g.get("game", {}).get("date"),
                    "home": (teams.get("home") or {}).get("name") or (g.get("home") or {}).get("name"),
                    "away": (teams.get("away") or {}).get("name") or (g.get("away") or {}).get("name"),
                })

        out: List[Dict[str, Any]] = []

        # ---- 2) per-game odds -> normalize -> picks ----
        for game in games:
            fid = game["fixture_id"]
            try:
                extra = {}
                if bookmaker_id is not None:
                    extra["bookmaker"] = bookmaker_id

                odds_payload = client.odds_for_fixture(league, int(fid), **extra)

                if raw_odds:
                    normalized = None
                else:
                    normalized = normalize_odds(odds_payload, preferred_bookmaker_id=bookmaker_id)

                if _HAS_PICKER and normalized is not None:
                    picks = _compute_picks(
                        league=league, normalized_odds=normalized, bookmaker_id=bookmaker_id, min_edge=ev_threshold
                    )
                else:
                    picks = []

                out.append({
                    "fixture_id": fid,
                    "matchup": {"home": game["home"], "away": game["away"], "date": game["date"]},
                    "odds": odds_payload if raw_odds else normalized,
                    "picks": picks,
                })
            except Exception as e:
                out.append({
                    "fixture_id": fid,
                    "matchup": {"home": game.get("home"), "away": game.get("away"), "date": game.get("date")},
                    "error": str(e),
                })

        # Optional: sort each game's picks by edge (already done in picker), or
        # filter games with at least one pick above threshold:
        return {
            "league": league,
            "date": qdate,
            "count_games": len(out),
            "items": out,
        }

    finally:
        client.close()
