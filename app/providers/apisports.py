# app/providers/apisports.py
import os
from typing import Optional, Literal, List
from datetime import datetime, timezone
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "nfl", "ncaaf", "ncaab"]

# Base URLs (override on Render if you want)
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")
AMFOOTBALL_BASE = os.getenv("APISPORTS_BASE_AMFOOTBALL", "https://v1.american-football.api-sports.io")

# API-SPORTS league ids (these are correct for these products)
LEAGUE_ID = {"nba": "12", "ncaab": "7", "nfl": "1", "ncaaf": "2"}

def _normalize_season(league: League, season: Optional[str]) -> Optional[str]:
    if not season:
        return None
    s = str(season)
    # Basketball wants the starting year only (e.g., "2024" out of "2024-2025")
    if league in ("nba", "ncaab") and "-" in s:
        s = s.split("-")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

def _base_and_path(league: League) -> tuple[str, str]:
    # Basketball => /games ; American Football => /games
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    return AMFOOTBALL_BASE, "games"

class ApiSportsProvider:
    def __init__(self, key: str):
        self.key = key
        self.client = httpx.AsyncClient(timeout=20)

    def _headers(self) -> dict:
        return {"x-apisports-key": self.key}

    async def list_games(
        self,
        league: League,
        *,
        date: Optional[str] = None,     # YYYY-MM-DD
        season: Optional[str] = None,   # NBA/NCAAB: starting year e.g. 2024; NFL/NCAAF: 2024
        limit: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"
        params: dict = {"league": LEAGUE_ID[league], "timezone": "UTC"}

        if date:
            params["date"] = date
        norm_season = _normalize_season(league, season)
        if norm_season:
            params["season"] = norm_season
        if "date" not in params and "season" not in params:
            params["date"] = datetime.now(timezone.utc).date().isoformat()

        out: List[MarketBook] = []
        page = 1
        while True:
            params["page"] = page
            r = await self.client.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            body = r.json()
            data = body.get("response", [])
            paging = body.get("paging", {})

            out.extend(_map_games(league, data))
            if limit and len(out) >= limit:
                return out[:limit]

            cur = int(paging.get("current", page))
            tot = int(paging.get("total", page))
            if cur >= tot or not data:
                break
            page += 1

        return out if not limit else out[:limit]

    async def list_games_range(
        self,
        league: League,
        *,
        date_from: Optional[str] = None,  # YYYY-MM-DD
        date_to: Optional[str] = None,    # YYYY-MM-DD
        season_from: Optional[str] = None,
        season_to: Optional[str] = None,
        limit: Optional[int] = 500,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"
        out: List[MarketBook] = []

        # Strategy 1: date window
        if date_from or date_to:
            params: dict = {"league": LEAGUE_ID[league], "timezone": "UTC"}
            if date_from: params["from"] = date_from
            if date_to: params["to"] = date_to

            page = 1
            while True:
                params["page"] = page
                r = await self.client.get(url, headers=self._headers(), params=params)
                r.raise_for_status()
                body = r.json()
                data = body.get("response", [])
                paging = body.get("paging", {})
                out.extend(_map_games(league, data))
                if limit and len(out) >= limit:
                    return out[:limit]
                cur = int(paging.get("current", page))
                tot = int(paging.get("total", page))
                if cur >= tot or not data:
                    break
                page += 1
            return out if not limit else out[:limit]

        # Strategy 2: season range (iterate)
        s_from = _normalize_season(league, season_from)
        s_to = _normalize_season(league, season_to)
        if s_from and not s_to: s_to = s_from
        if s_to and not s_from: s_from = s_to

        if s_from and s_to:
            for yr in range(int(s_from), int(s_to) + 1):
                params = {"league": LEAGUE_ID[league], "timezone": "UTC", "season": str(yr)}
                page = 1
                while True:
                    params["page"] = page
                    r = await self.client.get(url, headers=self._headers(), params=params)
                    r.raise_for_status()
                    body = r.json()
                    data = body.get("response", [])
                    paging = body.get("paging", {})
                    out.extend(_map_games(league, data))
                    if limit and len(out) >= limit:
                        return out[:limit]
                    cur = int(paging.get("current", page))
                    tot = int(paging.get("total", page))
                    if cur >= tot or not data:
                        break
                    page += 1

        if not (date_from or date_to or s_from or s_to):
            return await self.list_games(league, limit=limit)
        return out if not limit else out[:limit]

    async def aclose(self):
        await self.client.aclose()

def _map_games(league: League, data: list) -> List[MarketBook]:
    out: List[MarketBook] = []
    for g in data:
        gid = str(g.get("id") or g.get("fixture", {}).get("id") or g.get("game", {}).get("id") or "unknown")
        start_iso = (g.get("date") or g.get("fixture", {}).get("date") or g.get("game", {}).get("date") or "")
        home = g.get("teams", {}).get("home") or g.get("home", {})
        away = g.get("teams", {}).get("away") or g.get("away", {})
        home_name = home.get("name", "Home")
        away_name = away.get("name", "Away")
        home_abbr = home.get("code", "HOME")
        away_abbr = away.get("code", "AWY")     # <-- fixed

        game = Game(
            game_id=gid,
            league=league,
            start_iso=start_iso,
            home=Team(id=f"{gid}-H", name=home_name, abbr=home_abbr),
            away=Team(id=f"{gid}-A", name=away_name, abbr=away_abbr),
        )
        out.append(MarketBook(game=game, lines=[]))
    return out
