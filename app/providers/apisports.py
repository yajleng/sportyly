# app/providers/apisports.py
import os
from typing import Optional, Literal, List, Tuple, Any
import httpx
from datetime import date

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

# API-Sports league ids
BASKETBALL_LEAGUE_ID = {"nba": "12", "ncaab": "7"}
FOOTBALL_LEAGUE_ID = {"nfl": "1", "ncaaf": "2"}

def _base_and_path(league: League) -> Tuple[str, str]:
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    return FOOTBALL_BASE, "fixtures"

def _expand_basketball_season(s: Optional[str]) -> Optional[str]:
    """NBA/NCAAB want YYYY-YYYY. If caller sends YYYY, expand to YYYY-(YYYY+1)."""
    if not s:
        return None
    s = str(s)
    if "-" in s:
        return s  # already expanded
    # single year -> expand
    try:
        y = int("".join(ch for ch in s if ch.isdigit()))
        return f"{y}-{y+1}"
    except Exception:
        return None

def _coerce_gridiron_season(s: Optional[str]) -> Optional[str]:
    """NFL/NCAAF accept single starting year (YYYY). If YYYY-YYYY is passed, keep the first year."""
    if not s:
        return None
    s = str(s)
    if "-" in s:
        s = s.split("-")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

def _val_to_iso(v: Any) -> str:
    # API-Sports sometimes returns a dict with 'date'/'utc'
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
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
            start_iso = _val_to_iso(
                g.get("date")
                or g.get("fixture", {}).get("date")
                or g.get("game", {}).get("date")
                or ""
            )
            teams = g.get("teams") or {}
            home = teams.get("home") or g.get("home", {}) or {}
            away = teams.get("away") or g.get("away", {}) or {}
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
            print(f"[apisports] skip row due to mapping error: {e} | keys={list(g.keys())}")
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
        date: Optional[str] = None,
        season: Optional[str] = None,
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params: dict = {"timezone": "UTC"}

        if league in ("nba", "ncaab"):
            params["league"] = BASKETBALL_LEAGUE_ID[league]
            if season:
                params["season"] = _expand_basketball_season(season)
        elif league in ("nfl", "ncaaf"):
            params["league"] = FOOTBALL_LEAGUE_ID[league]
            if season:
                params["season"] = _coerce_gridiron_season(season)
        else:  # soccer
            if soccer_league_id:
                params["league"] = str(soccer_league_id)
            if season:
                params["season"] = _coerce_gridiron_season(season)

        if date:
            # basketball uses 'date', football fixtures uses 'date' as well
            params["date"] = date

        out: List[MarketBook] = []
        page = 1
        while True:
            params["page"] = page
            r = await self.client.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            body = r.json()
            batch = body.get("response", []) or []
            if not batch:
                print(f"[apisports] empty batch page={page} url={url} params={params}")
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

        # Date window
        if date_from or date_to:
            params: dict = {"timezone": "UTC"}
            if league in ("nba", "ncaab"):
                params["league"] = BASKETBALL_LEAGUE_ID[league]
            elif league in ("nfl", "ncaaf"):
                params["league"] = FOOTBALL_LEAGUE_ID[league]
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
                batch = body.get("response", []) or []
                out.extend(_map_games(league, batch))
                if limit and len(out) >= limit:
                    return out[:limit]
                pg = body.get("paging") or {}
                if int(pg.get("current", page)) >= int(pg.get("total", page)) or not batch:
                    break
                page += 1
            return out if not limit else out[:limit]

        # Season window
        if league in ("nba", "ncaab"):
            # expand both ends for basketball
            if season_from:
                season_from = _expand_basketball_season(season_from)
            if season_to:
                season_to = _expand_basketball_season(season_to)
        else:
            if season_from:
                season_from = _coerce_gridiron_season(season_from)
            if season_to:
                season_to = _coerce_gridiron_season(season_to)

        if season_from and not season_to:
            season_to = season_from
        if season_to and not season_from:
            season_from = season_to

        if season_from and season_to:
            if league in ("nba", "ncaab"):
                # Iterate start years but send expanded form
                start_year = int(season_from.split("-")[0])
                end_year = int(season_to.split("-")[0])
                years = range(start_year, end_year + 1)
            else:
                years = range(int(season_from), int(season_to) + 1)

            for yr in years:
                params: dict = {"timezone": "UTC"}
                if league in ("nba", "ncaab"):
                    params["league"] = BASKETBALL_LEAGUE_ID[league]
                    params["season"] = f"{yr}-{yr+1}"
                elif league in ("nfl", "ncaaf"):
                    params["league"] = FOOTBALL_LEAGUE_ID[league]
                    params["season"] = str(yr)
                else:
                    if soccer_league_id:
                        params["league"] = str(soccer_league_id)
                    params["season"] = str(yr)

                page = 1
                while True:
                    params["page"] = page
                    r = await self.client.get(url, headers=self._headers(), params=params)
                    r.raise_for_status()
                    body = r.json()
                    batch = body.get("response", []) or []
                    out.extend(_map_games(league, batch))
                    if limit and len(out) >= limit:
                        return out[:limit]
                    pg = body.get("paging") or {}
                    if int(pg.get("current", page)) >= int(pg.get("total", page)) or not batch:
                        break
                    page += 1

        return out if not limit else out[:limit]

    async def aclose(self):
        await self.client.aclose()
