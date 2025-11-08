# app/providers/apisports.py
import os
from typing import Optional, Literal, List, Tuple, Any
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

BASKETBALL_LEAGUE_ID = {"nba": "12", "ncaab": "7"}
FOOTBALL_LEAGUE_ID = {"nfl": "1", "ncaaf": "2"}  # API-Sports “fixtures” leagues

def _base_and_path(league: League) -> Tuple[str, str]:
    # NBA/NCAAB -> basketball/games, NFL/NCAAF/Soccer -> football/fixtures
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    return FOOTBALL_BASE, "fixtures"

def _val_to_iso(v: Any) -> str:
    # API-Sports can return a plain string or a dict with “date”
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
            print(f"[apisports] skip row: {e} | keys={list(g.keys())}")
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
        date: Optional[str] = None,           # YYYY-MM-DD (optional)
        season: Optional[str] = None,         # pass through as caller provided
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params: dict = {"timezone": "UTC"}

        if league in ("nba", "ncaab"):
            params["league"] = BASKETBALL_LEAGUE_ID[league]
        elif league in ("nfl", "ncaaf"):
            params["league"] = FOOTBALL_LEAGUE_ID[league]
        else:  # soccer (caller supplies competition id)
            if soccer_league_id:
                params["league"] = str(soccer_league_id)

        if date:
            params["date"] = date
        if season:
            params["season"] = str(season)  # no normalization — send as given

        out: List[MarketBook] = []
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
        # Keep range support, but still “pass-through”: we only translate params,
        # no year math beyond iterating seasons if both bounds are provided.
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

        # Season window (pass-through; if caller provides single year strings, we just send them)
        if season_from and not season_to:
            season_to = season_from
        if season_to and not season_from:
            season_from = season_to

        if season_from and season_to:
            # iterate start -> end inclusive by simple integer if both look like numbers,
            # otherwise just call once with season_from (keeps behavior predictable).
            try:
                start = int("".join(ch for ch in str(season_from) if ch.isdigit())[:4])
                end   = int("".join(ch for ch in str(season_to)   if ch.isdigit())[:4])
                seasons = [str(y) for y in range(start, end + 1)]
            except Exception:
                seasons = [str(season_from)]

            for s in seasons:
                params: dict = {"timezone": "UTC", "season": s}
                if league in ("nba", "ncaab"):
                    params["league"] = BASKETBALL_LEAGUE_ID[league]
                elif league in ("nfl", "ncaaf"):
                    params["league"] = FOOTBALL_LEAGUE_ID[league]
                else:
                    if soccer_league_id:
                        params["league"] = str(soccer_league_id)

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
