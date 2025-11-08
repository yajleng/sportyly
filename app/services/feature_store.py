
from typing import Dict, Any, List, Tuple
import math

def rolling_off_def_rating(team_stats: Dict[str, Any]) -> Tuple[float, float]:
    """
    Return simple offensive/defensive ratings normalized per game.
    Fallbacks keep the system robust if fields are missing for a league.
    """
    g = max(team_stats.get("games", 1), 1)
    points_for = team_stats.get("points_for") or team_stats.get("goals_for") or 0
    points_against = team_stats.get("points_against") or team_stats.get("goals_against") or 0
    off = points_for / g
    deff = points_against / g
    return off, deff

def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def ml_winprob(home_rating: float, away_rating: float) -> float:
    # Simple Bradley-Terry style transform
    return logistic(home_rating - away_rating)
