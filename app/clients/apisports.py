# app/clients/apisports.py
from __future__ import annotations

from typing import Dict, Any, Optional, Literal, Mapping
import httpx

from ..core.config import (
    get_base_for_league,
    get_league_id,
)

# Public type used by routers
League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]


class ApiSportsError(RuntimeError):
    pass


class ApiSportsClient:
    """
    Thin, uniform wrapper over API-SPORTS families.

    Soccer (API-Football v3) base: https://v3.football.api-sports.io
    American Football (NFL/NCAAF v1) base: https://v1.american-football.api-sports.io
    Basketball (NBA/NCAAB v1) base: https://v1.basketball.api-sports.io
    """

    # ------------ lifecycle ------------
    def __init__(self, api_key: str, timeout: float = 20.0):
        self._http = httpx.Client(
            timeout=timeout,
            headers={"x-apisports-key": api_key},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ApiSportsClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ------------ low-level helpers ------------
    def _base(self, league: League) -> str:
        return get_base_for_league(league)

    def _get(self, url: str, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        resp = self._http.get(url, params=params or {})
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = resp.text
            except Exception:
                pass
            raise ApiSportsError(f"GET {url} -> {resp.status_code}: {body}") from e
        return resp.json()

    # ------------ fixtures (by date / range) ------------
    def fixtures_by_date(
        self,
        league: League,
        date: str,                       # "YYYY-MM-DD"
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Daily slate for a league.
        Soccer: /fixtures?date=&league=&[season]
        v1 families: /games?date=&league=
        """
        base = self._base(league)

        if league == "soccer":
            lid = get_league_id("soccer", league_id)
            url = f"{base}/fixtures"
            params: Dict[str, Any] = {"date": date, "league": lid}
            if season is not None:
                params["season"] = season
        else:
            lid = get_league_id(league, league_id)
            url = f"{base}/games"
            params = {"date": date, "league": lid}

        return self._get(url, params)

    def fixtures_range(
        self,
        league: League,
        from_date: str,                  # "YYYY-MM-DD"
        to_date: str,                    # "YYYY-MM-DD"
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fixtures in a date window.
        Soccer: /fixtures?from=&to=&league=&[season]
        v1 families: /games?from=&to=&league=
        """
        base = self._base(league)

        if league == "soccer":
            lid = get_league_id("soccer", league_id)
            url = f"{base}/fixtures"
            params: Dict[str, Any] = {"from": from_date, "to": to_date, "league": lid}
            if season is not None:
                params["season"] = season
        else:
            lid = get_league_id(league, league_id)
            url = f"{base}/games"
            params = {"from": from_date, "to": to_date, "league": lid}

        return self._get(url, params)

    # ------------ injuries ------------
    def injuries(
        self,
        league: League,
        team: Optional[int] = None,
        player: Optional[int] = None,
        *,
        league_id: Optional[int] = None,
        season: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Unified injuries. Callers enforce league/param rules.
        Soccer: /injuries?league=&season[&team][&player]
        NFL/NCAAF: /injuries[?team][&player]
        NBA/NCAAB: not supported by API-SPORTS
        """
        base = self._base(league)

        if league == "soccer":
            url = f"{base}/injuries"
            params: Dict[str, Any] = {}
            if league_id is not None:
                params["league"] = league_id
            if season is not None:
                params["season"] = season
            if team is not None:
                params["team"] = team
            if player is not None:
                params["player"] = player
            return self._get(url, params)

        if league in ("nfl", "ncaaf"):
            url = f"{base}/injuries"
            params: Dict[str, Any] = {}
            if team is not None:
                params["team"] = team
            if player is not None:
                params["player"] = player
            return self._get(url, params)

        raise ApiSportsError(f"Injuries not available for league '{league}'")

    # ------------ odds for a fixture/game ------------
    def odds_for_fixture(
        self,
        league: League,
        fixture_id: int,
        *,
        bookmaker: Optional[int] = None,
        bet: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Soccer: /odds?fixture={id}[&bookmaker][&bet]
        v1 families: /odds?game={id}[&bookmaker][&bet]
        """
        base = self._base(league)

        if league == "soccer":
            url = f"{base}/odds"
            params: Dict[str, Any] = {"fixture": fixture_id}
        else:
            url = f"{base}/odds"
            params = {"game": fixture_id}

        if bookmaker is not None:
            params["bookmaker"] = bookmaker
        if bet is not None:
            params["bet"] = bet

        return self._get(url, params)

    # ------------ bookmakers ------------
    def bookmakers(self, league: League) -> Dict[str, Any]:
        """
        GET /odds/bookmakers (no params) for the league's family.
        """
        base = self._base(league)
        return self._get(f"{base}/odds/bookmakers")
