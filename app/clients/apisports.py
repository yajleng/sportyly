
import httpx
from typing import Any, Dict, Optional, Literal

League = Literal["nba", "nfl", "ncaaf", "ncaab", "soccer"]

# Base URLs vary by sport. Keep them centralized & easy to swap if API changes.
BASES: Dict[League, str] = {
    # Basketball (NBA, NCAAB) – API-SPORTS uses v1 for basketball
    "nba":    "https://v1.basketball.api-sports.io",
    "ncaab":  "https://v1.basketball.api-sports.io",
    # American Football – NFL/NCAAF (v1)
    "nfl":    "https://v1.american-football.api-sports.io",
    "ncaaf":  "https://v1.american-football.api-sports.io",
    # Soccer/Football (v3)
    "soccer": "https://v3.football.api-sports.io",
}

# League identifiers used by API-SPORTS (edit if your account uses different IDs)
LEAGUE_IDS: Dict[League, int] = {
    "nba": 12,       # Basketball NBA
    "ncaab": 7,      # Basketball NCAA
    "nfl": 1,        # American Football NFL
    "ncaaf": 2,      # American Football NCAAF
    # Soccer requires also a country/season in queries; league id example: EPL=39, MLS=253, UCL=2, etc.
    # You can pass a `league_id` override at call-time for soccer.
    "soccer": 39,
}

class ApiSportsClient:
    def __init__(self, api_key: str, timeout: float = 15.0):
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, headers={"x-apisports-key": api_key})

    def _base(self, league: League) -> str:
        return BASES[league]

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    # ---- Common calls ----
    def fixtures_by_date(self, league: League, date: str, season: Optional[int] = None,
                         league_id: Optional[int] = None, **kw) -> Dict[str, Any]:
        base = self._base(league)
        lid = league_id or LEAGUE_IDS[league]
        if league == "soccer":
            url = f"{base}/fixtures"
            params = {"league": lid, "date": date}
            if season: params["season"] = season
        elif league in ("nba", "ncaab"):
            url = f"{base}/games"
            params = {"league": lid, "date": date}
            if season: params["season"] = season
        else:  # nfl, ncaaf
            url = f"{base}/games"
            params = {"league": lid, "date": date}
            if season: params["season"] = season
        params.update(kw)
        return self._get(url, params)

    def odds_for_fixture(self, league: League, fixture_id: int, **kw) -> Dict[str, Any]:
        base = self._base(league)
        if league == "soccer":
            url = f"{base}/odds"
            params = {"fixture": fixture_id}
        else:
            url = f"{base}/odds"
            params = {"game": fixture_id}
        params.update(kw)
        return self._get(url, params)

    def standings(self, league: League, season: int, league_id: Optional[int] = None) -> Dict[str, Any]:
        base = self._base(league)
        lid = league_id or LEAGUE_IDS[league]
        if league == "soccer":
            return self._get(f"{base}/standings", {"league": lid, "season": season})
        else:
            return self._get(f"{base}/standings", {"league": lid, "season": season})

    def teams_stats(self, league: League, season: int, team_id: Optional[int] = None,
                    league_id: Optional[int] = None) -> Dict[str, Any]:
        base = self._base(league)
        lid = league_id or LEAGUE_IDS[league]
        params = {"league": lid, "season": season}
        if team_id: params["team"] = team_id
        if league == "soccer":
            url = f"{base}/teams/statistics"
        else:
            url = f"{base}/teams/statistics"
        return self._get(url, params)

    def players_stats(self, league: League, season: int, team_id: Optional[int] = None,
                      player_id: Optional[int] = None, page: int = 1, **kw) -> Dict[str, Any]:
        base = self._base(league)
        if league == "soccer":
            url = f"{base}/players"
            params = {"season": season, "team": team_id, "page": page}
        else:
            url = f"{base}/players"
            params = {"season": season, "team": team_id, "page": page}
        params.update({k: v for k, v in kw.items() if v is not None})
        return self._get(url, params)

    # Historical fixtures/odds — pass past dates/seasons
    def fixtures_range(self, league: League, from_date: str, to_date: str, season: Optional[int] = None,
                       league_id: Optional[int] = None, **kw) -> Dict[str, Any]:
        base = self._base(league)
        lid = league_id or LEAGUE_IDS[league]
        if league == "soccer":
            url = f"{base}/fixtures"
            params = {"league": lid, "from": from_date, "to": to_date}
            if season: params["season"] = season
        else:
            url = f"{base}/games"
            params = {"league": lid, "from": from_date, "to": to_date}
            if season: params["season"] = season
        params.update(kw)
        return self._get(url, params)
