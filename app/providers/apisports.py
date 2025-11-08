import os
from typing import Optional, Literal, List, Dict, Any
from datetime import datetime, timezone
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]

FOOTBALL_BASE   = os.getenv("APISPORTS_BASE_FOOTBALL",   "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

LEAGUE_ID = {
    "nba": "12",    # Basketball
    "ncaab": "7",   # NCAA Basketball
    "nfl": "1",     # American Football
    "ncaaf": "2",   # NCAA Football
    # soccer uses many competitions -> pass in via soccer_league_id
}

def _normalize_basketball_season(value: Optional[str]) -> Optional[str]:
    """
    API-SPORTS Basketball expects '2024-2025'.
    If the caller sends '2024', convert to '2024-2025'.
    Otherwise pass-through.
    """
    if not value:
        return None
    s = str(value)
    if "-" in s:
        return s
    # single year -> make a span
    try:
        y = int(s)
        return f"{y}-{y+1}"
    except Exception:
        return s

def _pick_start_iso(g: Dict[str, Any]) -> str:
    """
    Robust date picker:
    - Prefer plain 'date' if it's already a string
    - Else look into 'fixture.date' or 'game.date'
    - If any of those is a dict like {'date': '...', 'timezone': 'UTC', ...},
      extract the 'date' field.
    """
    # top-level 'date'
    d = g.get("date")
    if isinstance(d, str):
        return d
    if isinstance(d, dict) and isinstance(d.get("date"), str):
        return d["date"]

    # fixture.date
    fx = g.get("fixture")
    if isinstance(fx, dict):
        d = fx.get("date")
        if isinstance(d, str):
            return d
        if isinstance(d, dict) and isinstance(d.get("date"), str):
            return d["date"]

    # game.date
    gm = g.get("game")
    if isinstance(gm, dict):
        d = gm.get("date")
        if isinstance(d, str):
            return d
        if isinstance(d, dict) and isinstance(d.get("date"), str):
            return d["date"]

    return ""

def _map_games(league: League, data: list) -> List[MarketBook]:
    out: List[MarketBook] = []
    for g in data:
        gid = str(
            g.get("id")
            or (g.get("fixture") or {}).get("id")
            or (g.get("game") or {}).get("id")
            or "unknown"
        )

        start_iso = _pick_start_iso(g)

        # teams
        home = (g.get("teams") or {}).get("home") or g.get("home") or {}
        away = (g.get("teams") or {}).get("away") or g.get("away") or {}

        home_name = home.get("name") or "Home"
        away_name = away.get("name") or "Away"
        home_abbr = home.get("code") or home.get("abbr") or "HOME"
        away_abbr = away.get("code") or away.get("abbr") or "AWY"

        game = Game(
            game_id=gid,
            league=league,
            start_iso=start_iso,  # always a string now
            home=Team(id=f"{gid}-H", name=home_name, abbr=home_abbr),
            away=Team(id=f"{gid}-A", name=away_name, abbr=away_abbr),
        )
        out.append(MarketBook(game=game, lines=[]))
    return out

def _base_and_path(league: League) -> tuple[str, str]:
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    if league in ("nfl", "ncaaf"):
        return FOOTBALL_BASE, "fixtures"
    # soccer (football/soccer) lives on the football host too
    return FOOTBALL_BASE, "fixtures"

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
        date: Optional[str] = None,        # YYYY-MM-DD
        season: Optional[str] = None,      # nba/ncaab "2024-2025" (or "2024"), nfl/ncaaf "2024", soccer "2024"
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params: Dict[str, Any] = {"timezone": "UTC"}

        if league == "soccer":
            # soccer requires an explicit competition id
            if soccer_league_id is None:
                return []
            params["league"] = str(soccer_league_id)
        else:
            params["league"] = LEAGUE_ID[league]

        # season handling
        if league in ("nba", "ncaab"):
            season = _normalize_basketball_season(season)
        if season:
            params["season"] = season

        if date:
            params["date"] = date

        # default to today if neither season nor date was provided
        if "season" not in params and "date" not in params:
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
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        out: List[MarketBook] = []

        # DATE WINDOW (works for football, basketball, soccer)
        if date_from or date_to:
            params: Dict[str, Any] = {"timezone": "UTC"}
            if league == "soccer":
                if soccer_league_id is None:
                    return []
                params["league"] = str(soccer_league_id)
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
            return out[:limit] if limit else out

        # SEASON WINDOW (iterate seasons)
        s_from = season_from
        s_to   = season_to
        if league in ("nba", "ncaab"):
            s_from = _normalize_basketball_season(season_from)
            s_to   = _normalize_basketball_season(season_to)

        if s_from and not s_to:
            s_to = s_from
        if s
