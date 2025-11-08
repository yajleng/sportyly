
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    apisports_key: str
    default_league: str = "nba"
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
