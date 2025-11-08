# app/providers/apisports.py
import os
from typing import Optional, Literal, List, Tuple, Any
from datetime import datetime
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

# API-SPORTS league ids
BASKETBALL_LEAGUE_ID = {
    "nba": "12",
    "ncaab": "7",
}
FOOTBALL_LEAGUE_ID = {
    "nfl": "1",
    "ncaaf": "2",
}

# ---------------------------
# Helpers
# ---------------------------

def _bball_default_season_year() -> int:
    """
    NBA/NCAAB seasons start in the fall and use the *starting* year.
    E.g., Nov 2024 is season 2024 (2024-2025).
    """
    now = datetime.utcnow()
    return now.year if now.month >= 8 else now.year - 1

def _gridiron_default_season_year() -> int:
    """
    NFL/NCAAF season year matches the calendar year (regular season in the fall).
    """
    return datetime.utcnow().year

def _normalize_season(league: League, season: Optional[str]) -> Optional[str]:
    """
    Make season a pure start year string for API-SPORTS.
    NBA/NCAAB accept either "2024" or "2024-2025" -> we store "2024".
    NFL/NCAAF are just "2024".
    Soccer varies by competition; caller controls it (we still accept digits only).
    """
    if not season:
        return None
    s = str(season)
    if league in ("nba", "ncaab") and "-" in s:
        s = s.split("-")[0]  # "2024-2025" -> "2024"
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

def _base_and_path(league: League) -> Tuple[str, str]:
    # Basketball uses /games on v1.basketball host.
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    # NFL, NCAAF and Soccer use /fixtures on v3.football host.
    return FOOTBALL_BASE, "fixtures"

def _val_to_iso(v: Any) -> str:
    """
    API-SPORTS sometimes returns a string, and sometimes a dict like:
      {"timezone":"UTC","date":"2024-10-01T00:00:00+00:00","timestamp": 172...}
    We always convert to the ISO string.
    """
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
            # Don't fail the whole response for one bad row
            print(f"[apisports] skip row due to mapping error: {e} | keys={list(g.keys())}")
            continue
    return out

def _add_common_params(
    league: League,
    *,
    date: Optional[str] = None,
    season: Optional[str] = None,
    soccer_league_id: Optional[int] = None,
) -> dict:
    """
    Prepare the minimal param set that actually returns data for each sport.
    - Basketball: MUST have league + season (or date).
    - NFL/NCAAF: MUST have league + season (or date).
    - Soccer: MUST have league (competition id) + usually season or date.
    If the caller doesn’t provide season/date, we insert sensible defaults.
    """
    params: dict = {"timezone": "UTC"}

    if league in ("nba", "ncaab"):
        params["league"] = BASKETBALL_LEAGUE_ID[league]
        if date:
            params["date"] = date
        else:
            norm = _normalize_season(league, season)
            if not norm:
                norm = str(_bball_default_season_year())
            params["season"] = norm
        return params

    if league in ("nfl", "ncaaf"):
        params["league"] = FOOTBALL_LEAGUE_ID[league]
        if date:
            params["date"] = date
        else:
            norm = _normalize_season(league, season)
            if not norm:
                norm = str(_gridiron_default_season_year())
            params["season"] = norm
        return params

    # Soccer
    if league == "soccer":
        # You must specify a competition id to get anything useful (e.g. EPL=39, MLS=253)
        if soccer_league_id:
            params["league"] = str(soccer_league_id)
        if date:
            params["date"] = date
        else:
            # We’ll pass season only if provided and valid; soccer season rules vary by league.
            norm = _normalize_season(league, season)
            if norm:
                params["season"] = norm
        return params

    return params

# ---------------------------
# Provider
# ---------------------------

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
        season: Optional[str] = None,          # NBA/NCAAB: 2024 or 2024-2025; NFL/NCAAF: 2024; Soccer: varies
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params = _add_common_params(
            league, date=date, season=season, soccer_league_id=soccer_league_id
        )

        out: List[MarketBook] = []
        page = 1
        # keep an upper bound just in case paging metadata is weird
        MAX_PAGES = 50

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
            if cur >= tot or not batch or page >= MAX_PAGES:
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

        # ----------------
        # Date window
        # ----------------
        if date_from or date_to:
            params = _add_common_params(
                league, soccer_league_id=soccer_league_id
            )
            # for range, API uses "from"/"to"
            if date_from:
                params["from"] = date_from
            if date_to:
                params["to"] = date_to

            page = 1
            MAX_PAGES = 100
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
                if cur >= tot or not batch or page >= MAX_PAGES:
                    break
                page += 1
            return out if not limit else out[:limit]

        # ----------------
        # Season window
        # ----------------
        s_from = _normalize_season(league, season_from)
        s_to = _normalize_season(league, season_to)
        if s_from and not s_to:
            s_to = s_from
        if s_to and not s_from:
            s_from = s_to

        if s_from and s_to:
            for yr in range(int(s_from), int(s_to) + 1):
                params = _add_common_params(
                    league, season=str(yr), soccer_league_id=soccer_league_id
                )

                page = 1
                MAX_PAGES = 100
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
                    if cur >= tot or not batch or page >= MAX_PAGES:
                        break
                    page += 1

        # If nothing specified, we won't guess a broad historical range.
        return out if not limit else out[:limit]

    async def aclose(self):
        await self.client.aclose()
