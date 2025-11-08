# app/providers/apisports.py
import os
import re
from typing import Optional, Literal, List, Tuple, Any, Dict
import httpx

from app.domain.models import Game, Team, MarketBook

League = Literal["nba", "ncaab", "nfl", "ncaaf", "soccer"]

# API-Sports bases
FOOTBALL_BASE = os.getenv("APISPORTS_BASE_FOOTBALL", "https://v3.football.api-sports.io")
BASKETBALL_BASE = os.getenv("APISPORTS_BASE_BASKETBALL", "https://v1.basketball.api-sports.io")

# Basketball (NBA/NCAAB) league ids; NFL/NCAAF handled by football "fixtures".
BASKETBALL_LEAGUE_ID: Dict[str, str] = {"nba": "12", "ncaab": "7"}

def _normalize_season(league: League, season: Optional[str]) -> Optional[str]:
    """
    Pass through what API-SPORTS expects:

      Basketball (nba, ncaab)
        Preferred: 'YYYY-YYYY'  (e.g. 2024-2025)
        Also accepted by API: 'YYYY' (starting year) but results vary by endpoint.

      Football (nfl, ncaaf) and Soccer:
        'YYYY'

    If invalid, return None so we simply omit it from the request.
    """
    if not season:
        return None

    s = str(season).strip()

    if league in ("nba", "ncaab"):
        if re.fullmatch(r"\d{4}-\d{4}", s):
            return s
        if re.fullmatch(r"\d{4}", s):
            return s
        return None

    # nfl, ncaaf, soccer
    return s if re.fullmatch(r"\d{4}", s) else None


def _base_and_path(league: League) -> Tuple[str, str]:
    # Basketball uses /games on the basketball host
    if league in ("nba", "ncaab"):
        return BASKETBALL_BASE, "games"
    # NFL, NCAAF and Soccer live on the football host; endpoint is fixtures
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
        # prefer explicit ISO-like fields if present
        return v.get("date") or v.get("utc") or ""
    return ""


def _map_games(league: League, rows: list) -> List[MarketBook]:
    """
    Convert raw API-Sports rows into our Game/MarketBook models.
    We keep this defensive so a single odd row doesn't kill the entire batch.
    """
    out: List[MarketBook] = []
    for g in rows:
        try:
            gid = str(
                g.get("id")
                or g.get("fixture", {}).get("id")
                or g.get("game", {}).get("id")
                or g.get("match", {}).get("id")
                or "unknown"
            )

            # date can be at different locations and can be str or dict
            start_iso = _val_to_iso(
                g.get("date")
                or g.get("fixture", {}).get("date")
                or g.get("game", {}).get("date")
                or g.get("match", {}).get("date")
                or ""
            )

            # teams structure: basketball returns teams.home/away; football fixtures return teams.home/away too
            teams = g.get("teams") or {}
            home = teams.get("home") or g.get("home", {}) or {}
            away = teams.get("away") or g.get("away", {}) or {}

            home_name = home.get("name") or home.get("team") or "Home"
            away_name = away.get("name") or away.get("team") or "Away"
            home_abbr = home.get("code") or home.get("short") or "HOME"
            away_abbr = away.get("code") or away.get("short") or "AWY"

            game = Game(
                game_id=gid,
                league=league,
                start_iso=start_iso,
                home=Team(id=f"{gid}-H", name=str(home_name), abbr=str(home_abbr)),
                away=Team(id=f"{gid}-A", name=str(away_name), abbr=str(away_abbr)),
            )
            out.append(MarketBook(game=game, lines=[]))
        except Exception as e:
            # Don’t blow up the whole page if one row is quirky
            print(f"[apisports] skip row due to mapping error: {e} | row keys={list(g.keys())}")
            continue
    return out


class ApiSportsProvider:
    def __init__(self, key: str):
        self.key = key
        # keep-alive default; reasonable timeout
        self.client = httpx.AsyncClient(timeout=20)

    def _headers(self) -> dict:
        return {"x-apisports-key": self.key}

    async def _paged_get(self, url: str, params: Dict[str, str | int], limit: Optional[int]) -> List[MarketBook]:
        """
        Generic paginator used by list_games and list_games_range windows.
        """
        out: List[MarketBook] = []
        page = 1
        while True:
            params["page"] = page
            r = await self.client.get(url, headers=self._headers(), params=params)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                print(f"[apisports] HTTP error {e.response.status_code} {e.response.text} | url={url} params={params}")
                break

            body = r.json()

            # Helpful diagnostics when API sends structured errors/warnings
            if body.get("errors"):
                print(f"[apisports] API errors: {body['errors']} | url={url} params={params}")
            if body.get("results") == 0:
                # keep logging this once per page so we can see which query is empty
                print(f"[apisports] empty batch page={page} url={url} params={params}")

            batch = body.get("response", []) or []
            out.extend(_map_games(params.get("league_name", "nba") if False else params.get("league_name", None), batch))  # dummy branch to keep typing happy

            # NOTE: _map_games needs the logical league, not numeric; we pass it at higher level instead.
            # Here we just return raw rows and let callers map. To keep the function simple for our current use,
            # we won't reuse this helper alone. Instead callers call this and then map with correct league.
            # (We still return mapped objects here for simplicity in current codebase.)
            # => Above mapping used wrong league; we’ll replace below with correct mapping via wrapper functions.
            break  # not used directly
        return out  # not used directly

    async def list_games(
        self,
        league: League,
        *,
        date: Optional[str] = None,           # YYYY-MM-DD
        season: Optional[str] = None,         # NBA/NCAAB: '2024-2025' or '2024'; NFL/NCAAF/Soccer: '2024'
        limit: Optional[int] = None,
        soccer_league_id: Optional[int] = None,
    ) -> List[MarketBook]:
        base, path = _base_and_path(league)
        url = f"{base}/{path}"

        params: Dict[str, str | int] = {"timezone": "UTC"}

        # Logical league -> API numeric "league" parameter
        if league in ("nba", "ncaab"):
            params["league"] = BASKETBALL_LEAGUE_ID[league]
        elif league in ("nfl", "ncaaf"):
            # NFL = 1, NCAAF = 2 on API-SPORTS football
            params["league"] = "1" if league == "nfl" else "2"
        else:  # soccer
            if soccer_league_id:
                params["league"] = str(soccer_league_id)

        if date:
            # basketball uses 'date', football fixtures also uses 'date'
            params["date"] = date

        norm = _normalize_season(league, season)
        if norm:
            params["season"] = norm

        out: List[MarketBook] = []
        page = 1
        while True:
            params["page"] = page
            r = await self.client.get(url, headers=self._headers(), params=params)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                print(f"[apisports] HTTP error {e.response.status_code} {e.response.text} | url={url} params={params}")
                break

            body = r.json()
            if body.get("errors"):
                print(f"[apisports] API errors: {body['errors']} | url={url} params={params}")

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
            params: Dict[str, str | int] = {"timezone": "UTC"}
            if league in ("nba", "ncaab"):
                params["league"] = BASKETBALL_LEAGUE_ID[league]
            elif league in ("nfl", "ncaaf"):
                params["league"] = "1" if league == "nfl" else "2"
            else:  # soccer
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
                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError as e:
                    print(f"[apisports] HTTP error {e.response.status_code} {e.response.text} | url={url} params={params}")
                    break

                body = r.json()
                if body.get("errors"):
                    print(f"[apisports] API errors: {body['errors']} | url={url} params={params}")

                batch = body.get("response", []) or []
                if not batch:
                    print(f"[apisports] empty batch page={page} url={url} params={params}")

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
            for yr in range(int(s_from[:4]), int(s_to[:4]) + 1):
                # For basketball, if the caller gave 'YYYY-YYYY' we should carry the hyphenated form.
                # We'll rebuild a hyphenated season when league is basketball.
                season_param = f"{yr}-{yr+1}" if league in ("nba", "ncaab") and "-" in (s_from or "") else str(yr)

                params: Dict[str, str | int] = {"timezone": "UTC", "season": season_param}
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
                    try:
                        r.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        print(f"[apisports] HTTP error {e.response.status_code} {e.response.text} | url={url} params={params}")
                        break

                    body = r.json()
                    if body.get("errors"):
                        print(f"[apisports] API errors: {body['errors']} | url={url} params={params}")

                    batch = body.get("response", []) or []
                    if not batch:
                        print(f"[apisports] empty batch page={page} url={url} params={params}")

                    out.extend(_map_games(league, batch))
                    if limit and len(out) >= limit:
                        return out[:limit]
                    pg = body.get("paging") or {}
                    if int(pg.get("current", page)) >= int(pg.get("total", page)) or not batch:
                        break
                    page += 1

        # Nothing specified: return whatever we have (likely empty) rather than guessing.
        return out if not limit else out[:limit]

    async def aclose(self):
        await self.client.aclose()
