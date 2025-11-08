from typing import Literal, Optional
from pydantic import BaseModel

League = Literal["nba","nfl","ncaaf","ncaab"]
MarketType = Literal["spread","total","moneyline","team_total","quarter_total","half_total","player_prop"]

class Team(BaseModel):
    id: str
    name: str
    abbr: str

class Game(BaseModel):
    game_id: str
    league: League
    start_iso: str
    home: Team
    away: Team

class Price(BaseModel):
    bookmaker: str
    price: float                      # decimal odds preferred internally
    price_type: Literal["decimal","american"] = "decimal"

class Line(BaseModel):
    market: MarketType
    team_side: Optional[Literal["home","away"]] = None
    period: Optional[Literal["full","1h","2h","q1","q2","q3","q4"]] = "full"
    point: Optional[float] = None     # spread/total/prop line
    prices: list[Price]

class MarketBook(BaseModel):
    game: Game
    lines: list[Line]
