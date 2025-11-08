# app/api/v1/endpoints/vendor.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from app.deps import provider_dep
from app.core.config import settings

router = APIRouter()

@router.get("/vendor/games", summary="Fetch upcoming or listed games via provider")
async def vendor_games(
    league: str = Query(..., pattern="^(nba|ncaab|nfl|ncaaf|soccer)$"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD (UTC)"),
    season: Optional[str] = Query(None, description="NBA/NCAAB: 2024-2025 (preferred) or 2024; NFL/NCAAF/Soccer: 2024"),
    limit: Optional[int] = Query(25, ge=1, le=200),
    compact: bool = Query(False, description="Return only id, start, teams"),
    soccer_league_id: Optional[int] = Query(None, description="Soccer competition id (e.g. 39=EPL, 253=MLS)"),
    provider = Depends(provider_dep),
):
    try:
        books = await provider.list_games(
            league, date=date, season=season, limit=limit, soccer_league_id=soccer_league_id
        )
        if compact:
            return {
                "league": league,
                "count": len(books),
                "games": [
                    {
                        "game_id": b.game.game_id,
                        "start_iso": b.game.start_iso,
                        "home": {"name": b.game.home.name, "abbr": b.game.home.abbr},
                        "away": {"name": b.game.away.name, "abbr": b.game.away.abbr},
                    } for b in books
                ],
            }
        return {"league": league, "games": [b.game.model_dump() for b in books]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"provider_error: {e}")

@router.get("/vendor/games/history", summary="Historical games via provider (date window or season window)")
async def vendor_games_history(
    league: str = Query(..., pattern="^(nba|ncaab|nfl|ncaaf|soccer)$"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    season_from: Optional[str] = Query(None, description="NBA/NCAAB: 2024-2025 or 2024; NFL/NCAAF/Soccer: 2024"),
    season_to: Optional[str] = Query(None, description="Same format as season_from"),
    limit: Optional[int] = Query(500, ge=1, le=2000),
    compact: bool = Query(True, description="Return only id, start, teams (default true here)"),
    soccer_league_id: Optional[int] = Query(None, description="Soccer competition id (e.g. 39=EPL)"),
    provider = Depends(provider_dep),
):
    try:
        books = await provider.list_games_range(
            league,
            date_from=date_from, date_to=date_to,
            season_from=season_from, season_to=season_to,
            limit=limit, soccer_league_id=soccer_league_id
        )
        if compact:
            return {
                "league": league,
                "count": len(books),
                "games": [
                    {
                        "game_id": b.game.game_id,
                        "start_iso": b.game.start_iso,
                        "home": {"name": b.game.home.name, "abbr": b.game.home.abbr},
                        "away": {"name": b.game.away.name, "abbr": b.game.away.abbr},
                    } for b in books
                ],
            }
        return {"league": league, "games": [b.game.model_dump() for b in books]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"provider_error: {e}")

@router.get("/vendor/provider", summary="Show which provider is active (key masked)")
async def vendor_provider():
    return {
        "sports_provider": settings.sports_provider,
        "apisports_key": "set" if bool(settings.sports_api_key) else "not-set",
    }
