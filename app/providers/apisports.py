# app/providers/apisports.py
import os
from typing import Optional, Literal, List, Tuple, Dict
from datetime import datetime, timezone
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

# --- BASE URLS (override on Render via env vars) -----------------------------
BASKETBALL_BASE = os.getenv(
    "APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io"
)
AMFOOTBALL_BASE = os.getenv(  # **American Football** (NFL/NCAAF)
    "APISPORTS_BASE_AMFOOTBALL", "https://v1.american-football.api-sports.io"
)
SOCCER_BASE = os.getenv(     # API-FOOTBALL (soccer)
    "APISPORTS_BASE_SOCCER", "https://v3.football.api-sports.io"
)

# League IDs per API-Sports products
BBALL_LEAGUE_ID: Dict[str, str] = {"nba": "12", "ncaab": "7"}
AMFOOT_LEAGUE_ID: Dict[str, str] = {"nfl": "1", "ncaaf": "2"}
# Soccer uses competition IDs that you must pass via soccer_league_id (e.g., 39 = EPL, 253 = MLS)

def _normalize_season(league: League, season: Optional[str]) -> Optional[str]:
    """Basketball expects the **starting year** (e.g., '2024' from '2024-2025')."""
    if not season:
        return None
    s = str(season)
    if league in ("nba", "ncaab") and "-" in s:
        s = s.split("-")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

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

class ApiSportsProvider:
    """Unified adapter for API-SPORTS Basketball, American Football, and Soccer."""

    def __init__(self, key: str):
        self.key = key
        self.client = httpx.AsyncClient(timeout=20)

    def _headers(self) -> dict:
        return {"x-apisports-key": self.key}  # native API-Sports auth header

    # ---------------- Current/Upcoming (by date OR season) -------------------
    async def list_games(
        self,
        league: League,
        *,
        date: Optional[str] = None,            # YYYY-MM-DD
        season: Optional[str] = None,          # NBA/NCAAB: '2024' or '2024-2025'; NFL/NCAAF/Soccer: '2024'
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None # required when league='soccer'
    ) -> List[MarketBook]:

        if league in ("nba", "ncaab"):
            base, path = BASKETBALL_BASE, "games"
            params = {"league": BBALL_LEAGUE_ID[league], "timezone": "UTC"}
            if date:
                params["date"] = date
            ns = _normalize_season(league, season)
            if ns:
                params["season"] = ns

        elif league in ("nfl", "ncaaf"):
            base, path = AMFOOTBALL_BASE, "games"
            params = {"league": AMFOOT_LEAGUE_ID[league], "timezone": "UTC"}
            if date:
                params["date"] = date
            if season:
                params["season"] = season

        elif league == "soccer":
            if not soccer_league_id:
                return []  # nothing to query against
            base, path = SOCCER_BASE, "fixtures"
            params = {"league": soccer_league_id, "timezone": "UTC"}
            if date:
                params["date"] = date
            if season:
                params["season"] = season
        else:
            return []

        # Default to today's UTC date if no filter to avoid massive payloads
        if "date" not in params and "season" not in params:
            params["date"] = datetime.now(timezone.utc).date().isoformat()

        url = f"{base}/{path}"
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

    # ---------------- Historical (date window OR season window) --------------
    async def list_games_range(
        self,
        league: League,
        *,
        date_from: Optional[str] = None,  # YYYY-MM-DD
        date_to: Optional[str] = None,    # YYYY-MM-DD
        season_from: Optional[str] = None,
        season_to: Optional[str] = None,
        limit: Optional[int] = 500,
        soccer_league_id: Optional[int] = None
    ) -> List[MarketBook]:

        if league in ("nba", "ncaab"):
            base, path = BASKETBALL_BASE, "games"
            common = {"league": BBALL_LEAGUE_ID[league], "timezone": "UTC"}
            normalize = True
        elif league in ("nfl", "ncaaf"):
            base, path = AMFOOTBALL_BASE, "games"
            common = {"league": AMFOOT_LEAGUE_ID[league], "timezone": "UTC"}
            normalize = False
        elif league == "soccer":
            if not soccer_league_id:
                return []
            base, path = SOCCER_BASE, "fixtures"
            common = {"league": soccer_league_id, "timezone": "UTC"}
            normalize = False
        else:
            return []

        url = f"{base}/{path}"
        out: List[MarketBook] = []

        # Strategy A: date range using from/to (supported by all three)
        if date_from or date_to:
            params = dict(common)
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

        # Strategy B: iterate seasons
        s_from = _normalize_season(league, season_from) if normalize else season_from
        s_to   = _normalize_season(league, season_to)   if normalize else season_to
        if s_from and not s_to:
            s_to = s_from
        if s_to and not s_from:
            s_from = s_to

        if s_from and s_to:
            for yr in range(int(s_from), int(s_to) + 1):
                params = dict(common)
                params["season"] = str(yr)
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

        # No filters supplied → fall back to today's slice
        return await self.list_games(league, limit=limit, soccer_league_id=soccer_league_id)

    async def aclose(self):
        await self.client.aclose()
