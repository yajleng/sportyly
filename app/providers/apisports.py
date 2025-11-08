import os
from typing import Optional, Literal, List
from datetime import datetime, timezone
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

# Correct bases per API-SPORTS products
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")
AMERICAN_FB_BASE = os.getenv("APISPORTS_BASE_AMERICAN_FB", "https://v1.american-football.api-sports.io")
SOCCER_BASE = os.getenv("APISPORTS_BASE_SOCCER", "https://v3.football.api-sports.io")  # association football

# League ids per API-SPORTS (these are the common defaults)
BASKETBALL_LEAGUE_ID = {"nba": "12", "ncaab": "7"}
AMERICAN_FB_LEAGUE_ID = {"nfl": "1", "ncaaf": "2"}  # API-Sports American Football product

def _normalize_season_for_basketball(season: Optional[str]) -> Optional[str]:
    """NBA/NCAAB: they accept starting year (e.g., '2024') even if caller sends '2024-2025'."""
    if not season:
        return None
    s = str(season)
    if "-" in s:
        s = s.split("-")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

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
        date: Optional[str] = None,      # YYYY-MM-DD
        season: Optional[str] = None,    # NBA/NCAAB: '2024' or '2024-2025'; NFL/NCAAF/Soccer: '2024'
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        """
        Single-page convenience fetch; defaults to today's UTC date if no filter is supplied.
        """
        # Route by sport family
        if league in ("nba", "ncaab"):
            base, path = BASKETBALL_BASE, "games"
            params = {
                "league": BASKETBALL_LEAGUE_ID[league],
                "timezone": "UTC",
            }
            if date:
                params["date"] = date
            norm = _normalize_season_for_basketball(season)
            if norm:
                params["season"] = norm
        elif league in ("nfl", "ncaaf"):
            base, path = AMERICAN_FB_BASE, "games"
            params = {
                "league": AMERICAN_FB_LEAGUE_ID[league],
                "timezone": "UTC",
            }
            if date:
                params["date"] = date
            if season:
                params["season"] = season  # American football uses single year (e.g., 2024)
        else:  # soccer
            base, path = SOCCER_BASE, "fixtures"
            if not soccer_league_id:
                # Require explicit soccer competition to avoid huge pulls
                return []
            params = {"league": str(soccer_league_id), "timezone": "UTC"}
            if date:
                params["date"] = date
            if season:
                params["season"] = season

        # Fallback: keep payload small if caller sends no filter
        if "date" not in params and "season" not in params:
            params["date"] = datetime.now(timezone.utc).date().isoformat()

        url = f"{base}/{path}"
        r = await self.client.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        body = r.json()
        data = body.get("response", [])

        out: List[MarketBook] = _map_games(league, data)
        return out[:limit] if limit else out

    async def list_games_range(
        self,
        league: League,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        season_from: Optional[str] = None,
        season_to: Optional[str] = None,
        limit: Optional[int] = 500,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        """
        Paged fetch across a date or season window. Handles API pagination internally.
        """
        if league in ("nba", "ncaab"):
            base, path = BASKETBALL_BASE, "games"
            league_id = BASKETBALL_LEAGUE_ID[league]
        elif league in ("nfl", "ncaaf"):
            base, path = AMERICAN_FB_BASE, "games"
            league_id = AMERICAN_FB_LEAGUE_ID[league]
        else:
            base, path = SOCCER_BASE, "fixtures"
            if not soccer_league_id:
                return []
            league_id = str(soccer_league_id)

        url = f"{base}/{path}"
        out: List[MarketBook] = []

        # Strategy 1: date window (supported across products)
        if date_from or date_to:
            params = {"league": league_id, "timezone": "UTC"}
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
                out.extend(_map_games(league, data))
                if limit and len(out) >= limit:
                    return out[:limit]
                paging = body.get("paging", {})
                cur = int(paging.get("current", page))
                tot = int(paging.get("total", page))
                if cur >= tot or not data:
                    break
                page += 1
            return out[:limit] if limit else out

        # Strategy 2: season window (iterate seasons)
        s_from = _normalize_season_for_basketball(season_from) if league in ("nba", "ncaab") else season_from
        s_to = _normalize_season_for_basketball(season_to) if league in ("nba", "ncaab") else season_to
        if s_from and not s_to:
            s_to = s_from
        if s_to and not s_from:
            s_from = s_to

        if s_from and s_to:
            for yr in range(int(s_from), int(s_to) + 1):
                params = {"league": league_id, "season": str(yr), "timezone": "UTC"}
                page = 1
                while True:
                    params["page"] = page
                    r = await self.client.get(url, headers=self._headers(), params=params)
                    r.raise_for_status()
                    body = r.json()
                    data = body.get("response", [])
                    out.extend(_map_games(league, data))
                    if limit and len(out) >= limit:
                        return out[:limit]
                    paging = body.get("paging", {})
                    cur = int(paging.get("current", page))
                    tot = int(paging.get("total", page))
                    if cur >= tot or not data:
                        break
                    page += 1

        # If no filters, fall back to today
        if not (date_from or date_to or s_from or s_to):
            return await self.list_games(league, limit=limit, soccer_league_id=soccer_league_id)

        return out[:limit] if limit else out

    async def aclose(self):
        await self.client.aclose()

def _map_games(league: League, data: list) -> List[MarketBook]:
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
            league=league,
            start_iso=start_iso,
            home=Team(id=f"{gid}-H", name=home_name, abbr=home_abbr),
            away=Team(id=f"{gid}-A", name=away_name, abbr=away_abbr),
        )
        out.append(MarketBook(game=game, lines=[]))
    return out
