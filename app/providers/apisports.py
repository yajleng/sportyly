# app/providers/apisports.py
import os
from typing import Optional, Literal, List
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "nfl", "ncaaf", "ncaab"]

# Base URLs (override with env on Render)
FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

# API-SPORTS league ids (adjust if you use others)
LEAGUE_ID = {
    "nba": "12",    # Basketball
    "ncaab": "7",   # NCAA Basketball
    "nfl": "1",     # Football
    "ncaaf": "2",   # NCAA Football
}

class ApiSportsProvider:
    """
    Minimal API-SPORTS adapter that fetches game schedules and normalizes them
    to your domain models. Returns a List[MarketBook].
    """
    def __init__(self, key: str):
        self.key = key
        self.client = httpx.AsyncClient(timeout=15)

    def _headers(self) -> dict:
        # Direct API-SPORTS header (not RapidAPI)
        return {"x-apisports-key": self.key}

    async def list_games(
        self,
        league: League,
        *,
        date: Optional[str] = None,     # "YYYY-MM-DD"
        season: Optional[str] = None,   # NBA "2024-2025", NFL "2024", etc.
        limit: Optional[int] = None,
    ) -> List[MarketBook]:
        if league in ("nba", "ncaab"):
            base = BASKETBALL_BASE
            url = f"{base}/games"
        else:
            base = FOOTBALL_BASE
            url = f"{base}/fixtures"

        params: dict = {"league": LEAGUE_ID[league]}
        if date:
            params["date"] = date
        if season:
            params["season"] = season

        r = await self.client.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        data = r.json().get("response", [])

        out: List[MarketBook] = []
        for g in data:
            # Defensive extraction across sports
            gid = str(
                g.get("id")
                or g.get("fixture", {}).get("id")
                or g.get("game", {}).get("id")
                or "unknown"
            )
            start_iso = (
                g.get("date")
                or g.get("fixture", {}).get("date")
                or g.get("game", {}).get("date")
                or ""
            )
            home = g.get("teams", {}).get("home") or g.get("home", {})
            away = g.get("teams", {}).get("away") or g.get("away", {})
            home_name = home.get("name", "Home")
            away_name = away.get("name", "Away")
            home_abbr = home.get("code", "HOME")
            away_abbr = away.get("code", "AWY")

            game = Game(
                game_id=gid,
                league=league,
                start_iso=start_iso,
                home=Team(id=f"{gid}-H", name=home_name, abbr=home_abbr),
                away=Team(id=f"{gid}-A", name=away_name, abbr=away_abbr),
            )

            out.append(MarketBook(game=game, lines=[]))

            if limit and len(out) >= limit:
                break

        return out

    async def aclose(self):
        await self.client.aclose()
