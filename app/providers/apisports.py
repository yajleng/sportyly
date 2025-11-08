# app/providers/apisports.py
import os
from typing import Optional, Literal, List, Tuple, Any
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

# API-Sports league ids
BASKETBALL_LEAGUE_ID = {"nba": "12", "ncaab": "7"}
FOOTBALL_LEAGUE_ID = {"nfl": "1", "ncaaf": "2"}  # American football (not soccer)

def _normalize_season(league: League, season: Optional[str]) -> Optional[str]:
    """Basketball allows '2024-2025' but API expects the starting year '2024'."""
    if not season:
        return None
    s = str(season)
    if league in ("nba", "ncaab") and "-" in s:
        s = s.split("-")[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None

def _base_and_path(league: League) -> Tuple[str, str]:
    """Return (base, endpoint) for the given league."""
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    # NFL, NCAAF and Soccer share the football host; endpoint is 'fixtures'
    return FOOTBALL_BASE, "fixtures"

def _val_to_iso(v: Any) -> str:
    """
    Coerce API-Sports date value to ISO string.
    - Sometimes a string
    - Sometimes dict: {"timezone":"UTC","date":"2024-10-01T00:00:00+00:00","timestamp":...}
    """
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("date") or v.get("utc") or ""
    return ""

def _extract_teams(league: League, g: dict) -> Tuple[dict, dict]:
    """
    Return (home, away) team dicts in a league-agnostic way.
    Basketball uses 'visitors' instead of 'away'.
    Soccer/football/NFL use 'away'.
    """
    teams = g.get("teams", {}) or {}
    # basketball v1 uses 'visitors'
    home = teams.get("home") or g.get("home", {}) or {}
    away = teams.get("away") or teams.get("visitors") or g.get("away", {}) or {}
    return home, away

def _abbr(t: dict) -> str:
    """Pick a short code if present, otherwise fallback."""
    return (t.get("code") or t.get("short") or t.get("abbr") or "").strip() or (
        (t.get("name") or "X")[:3].upper()
    )

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

            # Normalize date to ISO
            raw_date = (
                g.get("date")
                or g.get("fixture", {}).get("date")
                or g.get("game", {}).get("date")
                or ""
            )
            start_iso = _val_to_iso(raw_date)

            # Normalize teams
            home_raw, away_raw = _extract_teams(league, g)
            home_name = home_raw.get("name") or "Home"
            away_name = away_raw.get("name") or "Away"
            home_abbr = _abbr(home_raw) or "HOME"
            away_abbr = _abbr(away_raw) or "AWY"

            game = Game(
                game_id=gid,
                league=league,
                start_iso=start_iso,
                home=Team(id=f"{gid}-H", name=home_name, abbr=home_abbr),
                away=Team(id=f"{gid}-A", name=away_name, abbr=away_abbr),
            )
            out.append(MarketBook(game=game, lines=[]))
        except Exception as e:
            # If anything odd appears in a single row, don't drop the whole response.
            print(f"[apisports] mapping error: {e} | row sample keys={list(g.keys())}")
            continue
    return out

class ApiSportsProvider:
    def __init__(self, key: str):
        self.key = key
        self.client = httpx.AsyncClient(timeout=20)

    def _headers(self) -> dict:
        # Native API-Sports auth header (NOT RapidAPI)
        return {"x-apisports-key": self.key}

    async def list_games(
        self,
        league: League,
        *,
        date: Optional[str] = None,             # YYYY-MM-DD
        season: Optional[str] = None,           # NBA/NCAAB '2024' or '2024-2025'; NFL/NCAAF/Soccer '2024'
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None, # e.g., EPL=39, MLS=253
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params: dict = {"timezone": "UTC"}
        if league in ("nba", "ncaab"):
            params["league"] = BASKETBALL_LEAGUE_ID[league]
        elif league in ("nfl", "ncaaf"):
            params["league"] = FOOTBALL_LEAGUE_ID[league]
        else:  # soccer
            if soccer_league_id:
                params["league"] = str(soccer_league_id)

        if date:
            params["date"] = date

        norm_season = _normalize_season(league, season)
        if norm_season:
            params["season"] = norm_season

        out: List[MarketBook] = []
        page = 1
        while True:
            params["page"] = page
            r = await self.client.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            body = r.json()
            batch = body.get("response", []) or []
            if not batch:
                # Helpful noise in Render logs while we iterate on params/allowlist
                print(f"[apisports] empty batch page={page} url={url} params={params}")
            out.extend(_map_games(league, batch))

            if limit and len(out) >= limit:
                return out[:limit]

            paging = body.get("paging") or {}
            cur = int(paging.get("current", page))
            tot = int(paging.get("total", page))
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

        # Strategy 1: date window
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
                if not batch:
                    print(f"[apisports] empty history batch page={page} url={url} params={params}")
                out.extend(_map_games(league, batch))
                if limit and len(out) >= limit:
                    return out[:limit]
                paging = body.get("paging") or {}
                cur = int(paging.get("current", page))
                tot = int(paging.get("total", page))
                if cur >= tot or not batch:
                    break
                page += 1
            return out if not limit else out[:limit]

        # Strategy 2: season window
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
                    if not batch:
                        print(f"[apisports] empty season batch page={page} season={yr} url={url} params={params}")
                    out.extend(_map_games(league, batch))
                    if limit and len(out) >= limit:
                        return out[:limit]
                    paging = body.get("paging") or {}
                    cur = int(paging.get("current", page))
                    tot = int(paging.get("total", page))
                    if cur >= tot or not batch:
                        break
                    page += 1

        return out if not limit else out[:limit]

    async def aclose(self):
        await self.client.aclose()
