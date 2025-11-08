import os
from typing import Optional, Literal, List
from datetime import datetime, timezone
import httpx

from app.domain.models import Game, Team, MarketBook

# Leagues we expose via the API
League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

# Base URLs (can be overridden in Render env)
BASKETBALL_BASE   = os.getenv("APISPORTS_BASE_BASKETBALL",   "https://v1.basketball.api-sports.io")
AMFOOTBALL_BASE   = os.getenv("APISPORTS_BASE_AMFOOTBALL",   "https://v1.american-football.api-sports.io")
SOCCER_BASE       = os.getenv("APISPORTS_BASE_SOCCER",       "https://v3.football.api-sports.io")

# Fixed league ids for these sports on API-SPORTS
LEAGUE_ID = {
    "nba":   "12",  # Basketball
    "ncaab": "7",
    "nfl":   "1",   # American Football
    "ncaaf": "2",
    # "soccer" varies by competition -> pass in via soccer_league_id
}

def _normalize_season_for_basketball_or_passthrough(league: str, season: Optional[str]) -> Optional[str]:
    if not season:
        return None
    s = str(season)
    # API-SPORTS accepts "2024" or "2024-2025" for basketball; we keep the first year
    if league in ("nba", "ncaab") and "-" in s:
        s = s.split("-")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

def _base_and_path(league: str) -> tuple[str, str]:
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    if league in ("nfl", "ncaaf"):
        return AMFOOTBALL_BASE, "games"
    # soccer
    return SOCCER_BASE, "fixtures"

def _map_games(league: str, data: list) -> List[MarketBook]:
    out: List[MarketBook] = []
    for g in data:
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
            league=league,  # type: ignore[arg-type]
            start_iso=start_iso,
            home=Team(id=f"{gid}-H", name=home_name, abbr=home_abbr),
            away=Team(id=f"{gid}-A", name=away_name, abbr=away_abbr),
        )
        out.append(MarketBook(game=game, lines=[]))
    return out

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
        date: Optional[str] = None,            # YYYY-MM-DD
        season: Optional[str] = None,          # basketball: starting year (e.g. 2024), nfl/ncaaf/soccer: 2024
        soccer_league_id: Optional[int] = None,# required for soccer (e.g. 39 EPL, 253 MLS, etc.)
        limit: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params: dict = {"timezone": "UTC"}

        if league == "soccer":
            # Must provide which soccer competition you want
            params["league"] = str(soccer_league_id or 39)  # default EPL=39 to make it easy
            if season:
                params["season"] = season
            if date:
                params["date"] = date
        else:
            params["league"] = LEAGUE_ID[league]
            norm_season = _normalize_season_for_basketball_or_passthrough(league, season)
            if norm_season:
                params["season"] = norm_season
            if date:
                params["date"] = date

            # If neither season nor date provided, default to "today" to avoid huge payloads
            if "date" not in params and "season" not in params:
                from datetime import datetime, timezone
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

            cur = int(paging.get("current", page) or page)
            tot = int(paging.get("total", page) or page)
            if cur >= tot or not data:
                break
            page += 1

        return out if not limit else out[:limit]

    async def list_games_range(
        self,
        league: League,
        *,
        date_from: Optional[str] = None,        # YYYY-MM-DD
        date_to: Optional[str] = None,          # YYYY-MM-DD
        season_from: Optional[str] = None,
        season_to: Optional[str] = None,
        soccer_league_id: Optional[int] = None, # required for soccer
        limit: Optional[int] = 500,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"
        out: List[MarketBook] = []

        # Prefer date window if provided (supported by all three families)
        if date_from or date_to:
            params: dict = {"timezone": "UTC"}
            if league == "soccer":
                params["league"] = str(soccer_league_id or 39)
            else:
                params["league"] = LEAGUE_ID[league]

            if date_from:
                params["from"] = date_from
            if date_to:
                params["to"] = date_to

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

                cur = int(paging.get("current", page) or page)
                tot = int(paging.get("total", page) or page)
                if cur >= tot or not data:
                    break
                page += 1

            return out if not limit else out[:limit]

        # Season loop (basketball/nfl/ncaaf/soccer)
        def norm(y: Optional[str]) -> Optional[str]:
            return _normalize_season_for_basketball_or_passthrough(league, y)

        s_from = norm(season_from)
        s_to   = norm(season_to)
        if s_from and not s_to: s_to = s_from
        if s_to and not s_from: s_from = s_to

        if s_from and s_to:
            for yr in range(int(s_from), int(s_to) + 1):
                params: dict = {"timezone": "UTC", "season": str(yr)}
                if league == "soccer":
                    params["league"] = str(soccer_league_id or 39)
                else:
                    params["league"] = LEAGUE_ID[league]

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

                    cur = int(paging.get("current", page) or page)
                    tot = int(paging.get("total", page) or page)
                    if cur >= tot or not data:
                        break
                    page += 1

        # Nothing provided → reuse list_games default behavior
        if not (date_from or date_to or s_from or s_to):
            return await self.list_games(league, limit=limit, soccer_league_id=soccer_league_id)

        return out if not limit else out[:limit]

    async def aclose(self):
        await self.client.aclose()
