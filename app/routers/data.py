# app/routers/data.py
from fastapi import APIRouter, Depends, Query
from app.clients.apisports import ApiSportsClient, League
from app.core.config import get_settings

router = APIRouter(prefix="/data", tags=["data"])

def _client() -> ApiSportsClient:
    settings = get_settings()
    return ApiSportsClient(api_key=settings.apisports_key)

@router.get("/injuries")
def injuries(
    league: League = Query(..., description="nba | nfl | ncaaf | ncaab | soccer"),
    date: str | None = Query(None, description="YYYY-MM-DD (optional)"),
    league_id_override: int | None = Query(None, description="Override default league id (mainly for soccer)"),
):
    """
    Pass a league and optional date to fetch current/dated injury reports
    from API-SPORTS. Returns raw provider JSON.
    """
    client = _client()
    try:
        return client.injuries(league, date=date, league_id=league_id_override)
    finally:
        client.close()
