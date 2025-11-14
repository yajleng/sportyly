# app/clients/apisports.py
from __future__ import annotations

from typing import Dict, Any, Optional, Literal, Mapping
import httpx

from ..core.config import (
    get_base_for_league,
    get_league_id,
)

# Public type used by routers
League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]


class ApiSportsError(RuntimeError):
    pass


class ApiSportsClient:
    """
    Thin, uniform wrapper over API-SPORTS families:

    - Soccer (API-Football v3)
      base: https://v3.football.api-sports.io
      fixtures:  GET /fixtures?date=YYYY-MM-DD&league={id}&season={yyyy}
                 GET /fixtures?from=YYYY-MM-DD&to=YYYY-MM-DD&league={id}&season={yyyy}
      injuries:  GET /injuries?league={id}&season={yyyy}[&team=][&player=]
      odds:      GET /odds?fixture={id}[&bookmaker=][&bet=]
      books:     GET /odds/bookmakers

    - American Football (NFL/NCAAF, v1)
      base: https://v1.american-football.api-sports.io
      fixtures:  GET /games?date=YYYY-MM-DD&league={id}
                 GET /games?from=YYYY-MM-DD&to=YYYY-MM-DD&league={id}
      injuries:  GET /injuries[?team=][&player=]
      odds:      GET /odds?game={id}[&bookmaker=][&bet=]
      books:     GET /odds/bookmakers

    - Basketball (NBA/NCAAB, v1)
      base: https://v1.basketball.api-sports.io
      fixtures:  GET /games?date=YYYY-MM-DD&league={id}
                 GET /games?from=YYYY-MM-DD&to=YYYY-MM-DD&league={id}
      injuries:  (not provided by API-SPORTS; don’t call)
      odds:      GET /odds?game={id}[&bookmaker=][&bet=]
      books:     GET /odds/bookmakers
    """

# app/core/config.py
from __future__ import annotations

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
BASES = {
    "basketball":        "https://v1.basketball.api-sports.io",
    "american_football": "https://v1.american-football.api-sports.io",
    "football":          "https://v3.football.api-sports.io",  # soccer
}

SUPPORTED: dict[League, dict] = {
    "nba":    {"sport": "basketball",        "league_id": 12},  # NBA
    "ncaab":  {"sport": "basketball",        "league_id": 7},   # NCAA Men
    "nfl":    {"sport": "american_football", "league_id": 1},   # NFL
    "ncaaf":  {"sport": "american_football", "league_id": 2},   # NCAAF
    "soccer": {"sport": "football",          "league_id": 39},  # default EPL (override per call)
}

def _sport_for(league: League) -> str:
    return SUPPORTED[league]["sport"]

def get_base_for_league(league: League) -> str:
    """Return base URL for the given league family."""
    return BASES[_sport_for(league)]

def get_league_id(league: League, override: Optional[int] = None) -> int:
    """Default league id unless an override is supplied."""
    return override or SUPPORTED[league]["league_id"]

    
    # ------------ lifecycle ------------
    def __init__(self, api_key: str, timeout: float = 20.0):
        self._http = httpx.Client(
            timeout=timeout,
            headers={"x-apisports-key": api_key},
        )

    def close(self) -> None:
        self._http.close()

    # ------------ low-level helpers ------------
    def _base(self, league: League) -> str:
        return get_base_for_league(league)

    def _get(self, url: str, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        resp = self._http.get(url, params=params or {})
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # include server body to help diagnose quickly
            body = ""
            try:
                body = resp.text
            except Exception:
                pass
            raise ApiSportsError(f"GET {url} -> {resp.status_code}: {body}") from e
        return resp.json()

    # ------------ fixtures (by date / range) ------------
    def fixtures_by_date(
        self,
        league: League,
        date: str,
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Daily slate for a league.
        """
        base = self._base(league)

        if league == "soccer":
            # v3: /fixtures requires league & season
            lid = get_league_id("soccer", league_id)
            if not season:
                raise ApiSportsError("soccer fixtures_by_date requires season")
            url = f"{base}/fixtures"
            params = {"date": date, "league": lid, "season": season}
        else:
            # v1: /games with league id (NFL=1, NCAAF=2, NBA=12, NCAAB=7)
            lid = get_league_id(league, league_id)
            url = f"{base}/games"
            params = {"date": date, "league": lid}

        return self._get(url, params)

    def fixtures_range(
        self,
        league: League,
        from_date: str,
        to_date: str,
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fixtures in a date window.
        """
        base = self._base(league)

        if league == "soccer":
            lid = get_league_id("soccer", league_id)
            if not season:
                raise ApiSportsError("soccer fixtures_range requires season")
            url = f"{base}/fixtures"
            params = {"from": from_date, "to": to_date, "league": lid, "season": season}
        else:
            lid = get_league_id(league, league_id)
            url = f"{base}/games"
            params = {"from": from_date, "to": to_date, "league": lid}

        return self._get(url, params)

    # ------------ injuries ------------
    def injuries(
        self,
        league: League,
        team: Optional[int] = None,
        player: Optional[int] = None,
        *,
        league_id: Optional[int] = None,
        season: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Unified injuries. Callers should enforce league/param rules.
        """
        base = self._base(league)

        if league == "soccer":
            if not (season and (league_id or True)):
                # season is mandatory; league is strongly recommended (competition).
                # We still allow league_id=None if the caller is intentionally broad,
                # but API typically expects league+season.
                pass
            url = f"{base}/injuries"
            params: Dict[str, Any] = {}
            if league_id is not None:
                params["league"] = league_id
            if season is not None:
                params["season"] = season
            if team is not None:
                params["team"] = team
            if player is not None:
                params["player"] = player
            return self._get(url, params)

        # american-football & basketball (v1)
        if league in ("nfl", "ncaaf"):
            url = f"{base}/injuries"
            params = {}
            if team is not None:
                params["team"] = team
            if player is not None:
                params["player"] = player
            return self._get(url, params)

        # NBA / NCAAB not supported by API-SPORTS
        raise ApiSportsError(f"Injuries not available for league '{league}'")

    # ------------ odds for a fixture/game ------------
    def odds_for_fixture(
        self,
        league: League,
        fixture_id: int,
        *,
        bookmaker: Optional[int] = None,
        bet: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetch odds for a specific fixture/game id.
        """
        base = self._base(league)

        if league == "soccer":
            url = f"{base}/odds"
            params = {"fixture": fixture_id}
        else:
            # v1 families use 'game'
            url = f"{base}/odds"
            params = {"game": fixture_id}

        if bookmaker is not None:
            params["bookmaker"] = bookmaker
        if bet is not None:
            params["bet"] = bet

        return self._get(url, params)

    # ------------ bookmakers ------------
    def bookmakers(self, league: League) -> Dict[str, Any]:
        """
        List bookmakers supported by API-SPORTS for the given family.
        (All three families expose GET /odds/bookmakers without params.)
        """
        base = self._base(league)
        url = f"{base}/odds/bookmakers"
        return self._get(url)
