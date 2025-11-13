# app/routers/picks.py
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from ..clients.apisports import ApiSportsClient, League
from ..core.config import get_settings
from ..services.odds import normalize_odds
from ..services.resolve import resolve_fixture_id

# If you already have a picker, import it. If not, we’ll return odds and an empty list of picks.
_HAS_PICKER = True
try:
    # adapt this import name to whatever your picker exposes
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


@router.get("/picks", summary="Compute picks (auto-resolves fixture when needed)")
def picks(
    league: League = Query(..., description="nba | nfl | ncaaf | ncaab | soccer"),
    # Path A: pass the game/fixture id directly (soccer fixture id OR AF game id)
    fixture_id: Optional[int] = Query(
        None, description="Soccer fixture id or American-football game id"
    ),
    # Path B (auto-resolve): provide date + at least one of home/away
    date: Optional[str] = Query(
        None, description="YYYY-MM-DD (use with home/away if fixture_id not given)"
    ),
    home: Optional[str] = Query(None, description="Home team name (partial OK)"),
    away: Optional[str] = Query(None, description="Away team name (partial OK)"),
    # Soccer-only helpers when resolving:
    league_id_override: Optional[int] = Query(
        None, description="Soccer competition (e.g., EPL=39)"
    ),
    season: Optional[int] = Query(None, description="Soccer season (e.g., 2025)"),
    # Odds filters / picker hints
    bookmaker_id: Optional[int] = Query(
        None, description="Prefer odds from this bookmaker id"
    ),
    bet_id: Optional[int] = Query(None, description="Filter to specific bet/market id"),
    raw_odds: bool = Query(
        False, description="If true, returns provider odds without normalization"
    ),
):
    """
    One call to:
    1) resolve (if needed) -> 2) fetch odds -> 3) normalize -> 4) compute picks (if picker available).
    """
    client = _client()
    try:
        resolved_note = None

        # ---------- 1) Resolve if user didn't provide fixture_id ----------
        if fixture_id is None:
            if not date or not (home or away):
                raise HTTPException(
                    status_code=422,
                    detail="Provide fixture_id OR (date and at least one of home/away) for auto-resolve.",
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
            fixture_id = res.get("fixture_id")
            resolved_note = res.get("picked_reason")
            if not fixture_id:
                # Surface candidates to your GPT/app for quick user confirmation
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Could not confidently resolve fixture; please confirm one of the candidates.",
                        "candidates": res.get("candidates", []),
                    },
                )

        # ----------
