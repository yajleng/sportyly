# app/core/config.py
from functools import lru_cache
from typing import Literal, Optional
from pydantic_settings import BaseSettings

# ----- Public types -----
League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]

# ----- App settings (env-driven) -----
class Settings(BaseSettings):
    apisports_key: str
    default_league: League = "nba"
    default_market: str = "us"
    cache_ttl_seconds: int = 120
    log_level: str = "INFO"

    class Config:
        env_prefix = ""
        env_file = ".env"
        case_sensitive = False

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

# ----- API-SPORTS static metadata -----
# Base URLs per sport family
BASES = {
    "basketball":        "https://v1.basketball.api-sports.io",
    "american_football": "https://v1.american-football.api-sports.io",
    "football":          "https://v3.football.api-sports.io",  # soccer
}

# Default league IDs per target league
SUPPORTED: dict[League, dict] = {
    "nba":   {"sport": "basketball",        "league_id": 12},  # NBA
    "ncaab": {"sport": "basketball",        "league_id": 7},   # NCAA (Men)
    "nfl":   {"sport": "american_football", "league_id": 1},   # NFL
    "ncaaf": {"sport": "american_football", "league_id": 2},   # NCAAF
    "soccer":{"sport": "football",          "league_id": 39},  # default EPL; override per request
}

# Preferred bookmaker when parsing odds (None = use first/aggregate)
BOOKMAKER_DEFAULT: Optional[str] = None

# ----- Helpers used by clients/services -----
def get_sport(league: League) -> str:
    return SUPPORTED[league]["sport"]

def get_base_for_league(league: League) -> str:
    return BASES[get_sport(league)]

def get_league_id(league: League, override: Optional[int] = None) -> int:
    return override or SUPPORTED[league]["league_id"]
