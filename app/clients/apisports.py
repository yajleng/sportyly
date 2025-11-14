# app/clients/apisports.py
from __future__ import annotations

from typing import Any, Dict, Optional
import httpx

from app.core.config import (
    League,              # Literal["nba","nfl","ncaaf","ncaab","soccer"]
    get_base_for_league, # base URL per league family
    get_league_id,       # default league id (or override)
)

class ApiSportsClient:
    def __init__(self, api_key: str, timeout: float = 20.0):
        self._client = httpx.Client(
            timeout=timeout,
            headers={"x-apisports-key": api_key},
        )

    # ---------- internal ----------
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = self._client.get(url, params=params or {})
        r.raise_for_status()
        return r.json()

    def _is_soccer(self, league: League) -> bool:
        return league == "soccer"

    # ---------- core calls ----------
    def fixtures_by_date(
        self,
        league: League,
        date: str,                     # "YYYY-MM-DD"
        season: Optional[int] = None,
        league_id: Optional[int] = None,
        **kw: Any,
    ) -> Dict[str, Any]:
        base = get_base_for_league(league)
        lid = get_league_id(league, league_id)
        if self._is_soccer(league):
            url = f"{base}/fixtures"
            params: Dict[str, Any] = {"league": lid, "date": date}
            if season is not None:
                params["season"] = season
        else:
            url = f"{base}/games"
            params = {"league": lid, "date": date}
            if season is not None:
                params["season"] = season
        params.update({k: v for k, v in (kw or {}).items() if v is not None})
        return self._get(url, params)

    def fixtures_range(
        self,
        league: League,
        from_date: str,                # "YYYY-MM-DD"
        to_date: str,                  # "YYYY-MM-DD"
        season: Optional[int] = None,
        league_id: Optional[int] = None,
        **kw: Any,
    ) -> Dict[str, Any]:
        base = get_base_for_league(league)
        lid = get_league_id(league, league_id)
        if self._is_soccer(league):
            url = f"{base}/fixtures"
            params: Dict[str, Any] = {"league": lid, "from": from_date, "to": to_date}
            if season is not None:
                params["season"] = season
        else:
            url = f"{base}/games"
            params = {"league": lid, "from": from_date, "to": to_date}
            if season is not None:
                params["season"] = season
        params.update({k: v for k, v in (kw or {}).items() if v is not None})
        return self._get(url, params)

    def odds_for_fixture(
        self,
        league: League,
        fixture_id: int,
        **kw: Any,
    ) -> Dict[str, Any]:
        base = get_base_for_league(league)
        if self._is_soccer(league):
            url = f"{base}/odds"
            params: Dict[str, Any] = {"fixture": fixture_id}
        else:
            url = f"{base}/odds"
            params = {"game": fixture_id}
        params.update({k: v for k, v in (kw or {}).items() if v is not None})
        return self._get(url, params)

    def bookmakers(self, league: League) -> Dict[str, Any]:
        """
        API-Sports bookmaker catalog for the league's sport family.
        Football (soccer) v3 and American Football/Basketball v1 use the same path.
        """
        base = get_base_for_league(league)
        return self._get(f"{base}/odds/bookmakers", {})

    def standings(
        self,
        league: League,
        season: int,
        league_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        base = get_base_for_league(league)
        lid = get_league_id(league, league_id)
        return self._get(f"{base}/standings", {"league": lid, "season": season})

    def teams_stats(
        self,
        league: League,
        season: int,
        team_id: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        base = get_base_for_league(league)
        lid = get_league_id(league, league_id)
        params: Dict[str, Any] = {"league": lid, "season": season}
        if team_id is not None:
            params["team"] = team_id
        return self._get(f"{base}/teams/statistics", params)

    def players_stats(
        self,
        league: League,
        season: int,
        team_id: Optional[int] = None,
        page: int = 1,
        league_id: Optional[int] = None,
        **kw: Any,
    ) -> Dict[str, Any]:
        base = get_base_for_league(league)
        lid = get_league_id(league, league_id)
        params: Dict[str, Any] = {"league": lid, "season": season, "page": page}
        if team_id is not None:
            params["team"] = team_id
        params.update({k: v for k, v in (kw or {}).items() if v is not None})
        return self._get(f"{base}/players", params)

    def injuries(
        self,
        league: League,
        date: Optional[str] = None,    # "YYYY-MM-DD" (ignored by AF)
        league_id: Optional[int] = None,
        **kw: Any,
    ) -> Dict[str, Any]:
        base = get_base_for_league(league)
        params: Dict[str, Any] = {}
        if league_id is not None:
            params["league"] = league_id
        if date is not None:
            params["date"] = date
        params.update({k: v for k, v in (kw or {}).items() if v is not None})
        return self._get(f"{base}/injuries", params)

    # ---------- lifecycle ----------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApiSportsClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
