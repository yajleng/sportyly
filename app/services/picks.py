
from typing import List, Dict, Any, Optional
from ..clients.apisports import ApiSportsClient, League
from ..schemas.common import Pick
from .feature_store import rolling_off_def_rating
from .models import fair_ml_prob, fair_spread, fair_total, american_to_prob, prob_to_american

def _extract_team_stats(stats_payload: Dict[str, Any], team_name: str) -> Dict[str, Any]:
    # Normalize a few common fields; adjust to your account’s schema if needed
    out = {"games": None, "points_for": None, "points_against": None}
    try:
        s = stats_payload.get("response") or stats_payload.get("statistics") or {}
        # Very loose mapping: adapt per sport if keys differ
        out["games"] = s.get("games", {}).get("played") or s.get("matches", {}).get("played")
        out["points_for"] = (s.get("points", {}) or s.get("goals", {})).get("for")
        out["points_against"] = (s.get("points", {}) or s.get("goals", {})).get("against")
    except Exception:
        pass
    return out

def build_picks(
    client: ApiSportsClient,
    league: League,
    date: str,
    season: Optional[int],
    bet_types: Optional[List[str]],
    league_id_override: Optional[int] = None
) -> List[Pick]:
    games = client.fixtures_by_date(league, date, season=season, league_id=league_id_override)
    fixtures = games.get("response") or games.get("results") or []

    picks: List[Pick] = []
    for g in fixtures:
        # Normalize fixture fields across sports
        if league == "soccer":
            fid = g["fixture"]["id"]
            home_name = g["teams"]["home"]["name"]
            away_name = g["teams"]["away"]["name"]
        else:
            fid = g.get("id") or g.get("game", {}).get("id") or g.get("fixture", {}).get("id")
            home = g.get("teams", {}).get("home") or g.get("home")
            away = g.get("teams", {}).get("away") or g.get("away")
            home_name = (home.get("name") if isinstance(home, dict) else home) or "HOME"
            away_name = (away.get("name") if isinstance(away, dict) else away) or "AWAY"

        # Team stats (very lightweight; expand with pace/possessions, etc.)
        # In many API-SPORTS sports, a single endpoint returns per-team statistics for a season.
        home_stats = client.teams_stats(league, season or 2024)
        away_stats = client.teams_stats(league, season or 2024)

        h_off, h_def = rolling_off_def_rating(home_stats)
        a_off, a_def = rolling_off_def_rating(away_stats)

        fair_p = fair_ml_prob(h_off, h_def, a_off, a_def)
        fair_home_price = prob_to_american(fair_p)

        # Pull market odds (first book)
        odds_payload = client.odds_for_fixture(league, fid)
        book_odds = None
        try:
            # Normalize odds shape; pick the first bookmaker
            resp = odds_payload.get("response") or []
            if resp:
                markets = resp[0].get("bookmakers") or resp[0].get("odds") or []
                book_odds = markets[0] if markets else None
        except Exception:
            pass

        # Moneyline pick
        if (not bet_types) or ("moneyline" in bet_types):
            # Assume US prices; fallback if not present
            market_home_price = None
            if book_odds:
                # Fill in from book_odds structure for your account
                pass
            edge = fair_p - (american_to_prob(market_home_price) if market_home_price else 0.0)
            picks.append(Pick(
                fixture_id=fid, league=league, bet_type="moneyline",
                selection=home_name, line=None, price=market_home_price or fair_home_price,
                edge=edge, win_prob=fair_p
            ))

        # Spread pick
        if (not bet_types) or ("spread" in bet_types):
            fair_sp = fair_spread(h_off, h_def, a_off, a_def)
            picks.append(Pick(
                fixture_id=fid, league=league, bet_type="spread",
                selection=home_name, line=fair_sp, price=None,
                edge=0.0, win_prob=fair_p  # replace edge when you map market spread
            ))

        # Total pick
        if (not bet_types) or ("total" in bet_types):
            fair_tot = fair_total(h_off, a_off)
            picks.append(Pick(
                fixture_id=fid, league=league, bet_type="total",
                selection="over" if fair_tot > 0 else "under",
                line=abs(fair_tot), price=None, edge=0.0, win_prob=fair_p
            ))

        # Half/Quarter totals & player props: add once you map API-SPORTS props markets for each league.

    return picks
