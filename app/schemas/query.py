from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict

League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown query params

class SlateQuery(_Strict):
    league: League
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD (defaults to today)")
    season: Optional[int] = Field(default=None, description="Season year")
    league_id_override: Optional[int] = Field(default=None, description="Soccer competition id")

class ResolveQuery(_Strict):
    league: League
    date: str
    home: Optional[str] = None
    away: Optional[str] = None
    league_id_override: Optional[int] = None
    season: Optional[int] = None

class OddsQuery(_Strict):
    league: League
    # either fixture_id OR (date + home/away)
    fixture_id: Optional[int] = None
    raw: bool = False
    bookmaker_id: Optional[int] = Field(default=None, description="provider 'bookmaker'")
    bet_id: Optional[int] = Field(default=None, description="provider 'bet'")
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    home: Optional[str] = None
    away: Optional[str] = None
    league_id_override: Optional[int] = None
    season: Optional[int] = None
