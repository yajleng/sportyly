from fastapi import APIRouter, Depends, HTTPException, Query
from app.deps import provider_dep

router = APIRouter()

@router.get("/vendor/games", summary="Fetch upcoming games via provider")
async def vendor_games(league: str = Query(..., pattern="^(nba|nfl|ncaaf|ncaab)$"),
                       provider = Depends(provider_dep)):
    try:
        books = [b async for b in provider.list_games(league)]
        return {"league": league, "games": [b.game.model_dump() for b in books]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"provider_error: {e}")
