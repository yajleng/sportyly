
from typing import Dict, Any, Tuple
from .feature_store import ml_winprob

def fair_ml_prob(home_off: float, home_def: float, away_off: float, away_def: float) -> float:
    home_rating = home_off - away_def
    away_rating = away_off - home_def
    return ml_winprob(home_rating, away_rating)

def fair_spread(home_off: float, home_def: float, away_off: float, away_def: float) -> float:
    # Expected margin proxy
    return (home_off - away_def) - (away_off - home_def)

def fair_total(home_off: float, away_off: float) -> float:
    # Very simple total proxy; refine per league with pace
    return home_off + away_off

def american_to_prob(price: float) -> float:
    if price >= 100:
        return 100 / (price + 100)
    elif price <= -100:
        return (-price) / (-price + 100)
    else:
        raise ValueError("bad american price")

def prob_to_american(p: float) -> int:
    if p <= 0 or p >= 1: return 0
    return int(round(100 * p / (1 - p))) if p < 0.5 else int(round(-100 * (1 - p) / p))
