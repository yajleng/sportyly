
from pydantic import BaseModel
from typing import Optional, List
from .common import League, BetType, Pick

class PicksRequest(BaseModel):
    league: League
    date: Optional[str] = None
    season: Optional[int] = None
    market: Optional[str] = "us"
    bet_types: Optional[List[BetType]] = None
    league_id_override: Optional[int] = None  # helpful for soccer

class PicksResponse(BaseModel):
    picks: List[Pick]
