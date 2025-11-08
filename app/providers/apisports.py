import os
from typing import Iterable, Literal
import httpx

from app.domain.models import Game, Team, Price, Line, MarketBook

League = Literal["nba","nfl","ncaaf","ncaab"]

FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

class ApiSportsProvider:
    def __init__(self, key: str):
        self.key = key
        self.client = httpx.AsyncClient(timeout=15)

    def _headers(self) -> dict:
        return {"x-apisports-key": self.key}

    async def list_games(self, league: League) -> Iterable[MarketBook]:
        # Pick a basic "games/fixtures" endpoint per sport. Fill league/season
        # with the ones you actually want later.
        if league in ("nba", "ncaab"):
            base = BASKETBALL_BASE
            url = f"{base}/games"
            params = {"league": "12" if league == "nba" else "7", "season": "2024-2025"}
        else:
            base = FOOTBALL_BASE
            url = f"{base}/fixtures"
            params = {"league": "1" if league == "nfl" else "2", "season": "2024"}  # adjust

        r = await self.client.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        data = r.json().get("response", [])

        out: list[MarketBook] = []
        for g in data:
            # Map common fields defensively across sports
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
            # Odds/lines come later (separate endpoints)
            out.append(MarketBook(game=game, lines=[]))
        return out
