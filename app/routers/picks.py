
from fastapi import APIRouter, Depends, Query
from ..schemas.picks import PicksRequest, PicksResponse
from ..clients.apisports import ApiSportsClient, League
from ..services.picks import build_picks
from ..deps import get_client

router = APIRouter(prefix="/picks", tags=["picks"])

@router.get("", response_model=PicksResponse)
def get_picks(
    league: League = Query("nba"),
    date: str = Query(..., description="YYYY-MM-DD"),
    season: int | None = None,
    bet_types: list[str] | None = Query(None),
    league_id_override: int | None = None,
    client: ApiSportsClient = Depends(get_client),
):
    picks = build_picks(client, league, date, season, bet_types, league_id_override)
    return {"picks": picks}
