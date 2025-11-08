# app/api/v1/endpoints/vendor.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import provider_dep
from app.core.config import settings

router = APIRouter()

@router.get("/vendor/games", summary="Fetch upcoming games via provider")
async def vendor_games(
    league: str = Query(..., pattern="^(nba|nfl|ncaaf|ncaab)$"),
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    season: Optional[str] = Query(None, description="e.g., 2024-2025 for NBA, 2024 for NFL"),
    limit: Optional[int] = Query(25, ge=1, le=200),
    compact: bool = Query(False, description="Return only id, start, teams"),
    provider = Depends(provider_dep),
):
    try:
        books = await provider.list_games(league, date=date, season=season, limit=limit)
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
                    }
                    for b in books
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
