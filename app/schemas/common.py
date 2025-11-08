
from pydantic import BaseModel, Field
from typing import Literal, Optional, List

League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]
BetType = Literal["moneyline", "spread", "total", "half_total", "quarter_total", "player_prop"]

class Odds(BaseModel):
    book: str
    home_price: float | None = None
    away_price: float | None = None
    spread: float | None = None
    total: float | None = None

class Fixture(BaseModel):
    fixture_id: int
    league: League
    season: int
    date: str
    home: str
    away: str

class Pick(BaseModel):
    fixture_id: int
    league: League
    bet_type: BetType
    selection: str
    line: float | None = None
    price: float | None = None
    edge: float = Field(..., description="Difference between model fair price and market")
    win_prob: float = Field(..., ge=0, le=1)
