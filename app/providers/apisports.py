# app/providers/apisports.py
import os
from typing import Optional, Literal, List, Tuple, Any
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

# Basketball (NBA/NCAAB) league ids; NFL/NCAAF handled by football "fixtures".
BASKETBALL_LEAGUE_ID = {"nba": "12", "ncaab": "7"}

def _normalize_season(league: League, season: Optional[str]) -> Optional[str]:
    if not season:
        return None
    s = str(season)
    if league in ("nba", "ncaab") and "-" in s:
        s = s.split("-")[0]  # e.g. "2024-2025" -> "2024"
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

def _base_and_path(league: League) -> Tuple[str, str]:
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    # NFL, NCAAF and Soccer all live on the football host; endpoint is fixtures
    return FOOTBALL_BASE, "fixtures"

def _val_to_iso(v: Any) -> str:
    """
    API-SPORTS sometimes returns a string, and sometimes a dict like:
      {"timezone":"UTC","date":"2024-10-01T00:00:00+00:00","timestamp": 172...}
    Make it a plain ISO string (or empty if unknown).
    """
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        # prefer explicit ISO fields if present
        return v.get("date") or v.get("utc") or ""
    return ""

def _map_games(league: League, rows: list) -> List[MarketBook]:
    out: List[MarketBook] = []
    for g in rows:
        try:
            gid = str(
                g.get("id")
                or g.get("fixture", {}).get("id")
                or g.get("game", {}).get("id")
                or "unknown"
            )

            # date can be at different locations and can be str or dict
            start_iso = _val_to_iso(
                g.get("date")
                or g.get("fixture", {}).get("date")
                or g.get("game", {}).get("date")
                or ""
            )

            # teams structure is consistent enough across endpoints
            home = g.get("teams", {}).get("home") or g.get("home", {})
            away = g.get("teams", {}).get("away") or g.get("away", {})
            home_name = home.get("name", "Home")
            away_name = away.get("name", "Away")
            home_abbr = home.get("code") or home.get("short") or "HOME"
            away_abbr = away.get("code") or away.get("short") or "AWY"

            game = Game(
                game_id=gid,
                league=league,
                start_iso=start_iso,
                home=Team(id=f"{gid}-H", name=home_name, abbr=home_abbr),
                away=Team(id=f"{gid}-A", name=away_name, abbr=away_abbr),
            )
            out.append(MarketBook(game=game, lines=[]))
        except Exception as e:
            # Don’t blow up the whole page if one row is quirky
            # (Uvicorn will show this in logs)
            print(f"[apisports] skip row due to mapping error: {e} | row keys={list(g.keys())}")
            continue
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
        date: Optional[str] = None,           # YYYY-MM-DD
        season: Optional[str] = None,         # NBA/NCAAB: '2024' or '2024-2025'; NFL/NCAAF/Soccer: '2024'
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params: dict = {"timezone": "UTC"}
        if league in ("nba", "ncaab"):
            params["league"] = BASKETBALL_LEAGUE_ID[league]
        elif league in ("nfl", "ncaaf"):
            # NFL = 1, NCAAF = 2 on API-SPORTS football
            params["league"] = "1" if league == "nfl" else "2"
        else:  # soccer
            # caller provides competition id (EPL=39, MLS=253, …)
            if soccer_league_id:
                params["league"] = str(soccer_league_id)

        if date:
            params["date"] = date

        norm = _normalize_season(league, season)
        if norm:
            params["season"] = norm

        # If user sends nothing, default to today's window would produce sparse data;
        # we’ll just let the API return whatever matches (may be empty).
        out: List[MarketBook] = []
        page = 1
        while True:
            params["page"] = page
            r = await self.client.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            body = r.json()
            batch = body.get("response", [])
            out.extend(_map_games(league, batch))

            if limit and len(out) >= limit:
                return out[:limit]

            pg = body.get("paging") or {}
            cur = int(pg.get("current", page))
            tot = int(pg.get("total", page))
            if cur >= tot or not batch:
                break
            page += 1

        return out if not limit else out[:limit]

    async def list_games_range(
        self,
        league: League,
        *,
        date_from: Optional[str] = None,   # YYYY-MM-DD
        date_to: Optional[str] = None,     # YYYY-MM-DD
        season_from: Optional[str] = None,
        season_to: Optional[str] = None,
        limit: Optional[int] = 500,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"
        out: List[MarketBook] = []

        # Date window
        if date_from or date_to:
            params: dict = {"timezone": "UTC"}
            if league in ("nba", "ncaab"):
                params["league"] = BASKETBALL_LEAGUE_ID[league]
            elif league in ("nfl", "ncaaf"):
                params["league"] = "1" if league == "nfl" else "2"
            else:
                if soccer_league_id:
                    params["league"] = str(soccer_league_id)

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
                batch = body.get("response", [])
                out.extend(_map_games(league, batch))
                if limit and len(out) >= limit:
                    return out[:limit]
                pg = body.get("paging") or {}
                if int(pg.get("current", page)) >= int(pg.get("total", page)) or not batch:
                    break
                page += 1
            return out if not limit else out[:limit]

        # Season window
        s_from = _normalize_season(league, season_from)
        s_to = _normalize_season(league, season_to)
        if s_from and not s_to:
            s_to = s_from
        if s_to and not s_from:
            s_from = s_to

        if s_from and s_to:
            for yr in range(int(s_from), int(s_to) + 1):
                params: dict = {"timezone": "UTC", "season": str(yr)}
                if league in ("nba", "ncaab"):
                    params["league"] = BASKETBALL_LEAGUE_ID[league]
                elif league in ("nfl", "ncaaf"):
                    params["league"] = "1" if league == "nfl" else "2"
                else:
                    if soccer_league_id:
                        params["league"] = str(soccer_league_id)

                page = 1
                while True:
                    params["page"] = page
                    r = await self.client.get(url, headers=self._headers(), params=params)
                    r.raise_for_status()
                    body = r.json()
                    batch = body.get("response", [])
                    out.extend(_map_games(league, batch))
                    if limit and len(out) >= limit:
                        return out[:limit]
                    pg = body.get("paging") or {}
                    if int(pg.get("current", page)) >= int(pg.get("total", page)) or not batch:
                        break
                    page += 1

        # Nothing specified: return empty rather than guessing
        return out if not limit else out[:limit]

    async def aclose(self):
        await self.client.aclose()
