# app/clients/apisports.py
from __future__ import annotations

from typing import Dict, Any, Optional, Literal, Mapping, List
import httpx

from ..core.config import get_base_for_league, get_league_id

# Keep the type local here to avoid any import cycles
League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]


class ApiSportsError(RuntimeError):
    pass


class ApiSportsClient:
    """
    Thin, uniform wrapper over API-SPORTS families.

    Soccer (API-Football v3): https://v3.football.api-sports.io
      - fixtures:  GET /fixtures?date=&league=&season=
                   GET /fixtures?from=&to=&league=&season=
      - injuries:  GET /injuries?league=&season[&team][&player]
      - odds:      GET /odds?fixture={id}[&bookmaker][&bet]
      - books:     GET /odds/bookmakers
      - stats:     GET /teams/statistics?team=&league=&season=
                   GET /fixtures/statistics?fixture=
                   GET /fixtures/players?fixture=

    American Football (NFL/NCAAF, v1): https://v1.american-football.api-sports.io
    Basketball (NBA/NCAAB, v1):       https://v1.basketball.api-sports.io
      - fixtures:  GET /games?date=&league=
                   GET /games?from=&to=&league=
      - injuries:  GET /injuries[?team][&player]  (NBA/NCAAB not supported)
      - odds:      GET /odds?game={id}[&bookmaker][&bet]
      - books:     GET /odds/bookmakers
      - stats:     GET /games/statistics/teams?id= | ids=
                   GET /games/statistics/players?id= | ids=
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

    @staticmethod
    def _clean(d: Mapping[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in d.items() if v is not None}

    @staticmethod
    def _join_ids(ids: Optional[List[int]]) -> Optional[str]:
        return "-".join(str(i) for i in ids) if ids else None

    # ------------ fixtures (by date / range) ------------
    def fixtures_by_date(
        self,
        league: League,
        date: str,                       # "YYYY-MM-DD"
        season: Optional[int] = None,
        league_id: Optional[int] = None,
    ) -> Dict[str, Any]:
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

    def odds_for_fixture_props(
        self,
        league: League,
        fixture_id: int,
        *,
        bet_id: Optional[int] = None,
        bookmaker: Optional[int] = None
    ) -> Dict[str, Any]:
        """Friendly alias for props pulls (for GPT readability)."""
        return self.odds_for_fixture(league, fixture_id, bookmaker=bookmaker, bet=bet_id)

    # ------------ bookmakers ------------
    def bookmakers(self, league: League) -> Dict[str, Any]:
        """GET /odds/bookmakers (no params) for the league's family."""
        base = self._base(league)
        return self._get(f"{base}/odds/bookmakers")

    # ------------ stats: soccer season team ------------
    def soccer_team_season_stats(
        self, *, team_id: int, league_id: int, season: int
    ) -> Dict[str, Any]:
        base = self._base("soccer")
        return self._get(
            f"{base}/teams/statistics",
            {"team": team_id, "league": league_id, "season": season},
        )

    # ------------ stats: game team + player (single) ------------
    def game_team_stats(self, league: League, game_id: int) -> Dict[str, Any]:
        base = self._base(league)
        if league == "soccer":
            return self._get(f"{base}/fixtures/statistics", {"fixture": game_id})
        return self._get(f"{base}/games/statistics/teams", {"id": game_id})

    def game_player_stats(self, league: League, game_id: int) -> Dict[str, Any]:
        base = self._base(league)
        if league == "soccer":
            return self._get(f"{base}/fixtures/players", {"fixture": game_id})
        return self._get(f"{base}/games/statistics/players", {"id": game_id})

    # ------------ stats: batch by ids (v1 families) ------------
    def game_team_stats_batch(self, league: League, game_ids: List[int]) -> Dict[str, Any]:
        base = self._base(league)
        ids = self._join_ids(game_ids)
        return self._get(f"{base}/games/statistics/teams", self._clean({"ids": ids}))

    def game_player_stats_batch(self, league: League, game_ids: List[int]) -> Dict[str, Any]:
        base = self._base(league)
        ids = self._join_ids(game_ids)
        return self._get(f"{base}/games/statistics/players", self._clean({"ids": ids}))
