# app/spec/apisports_map.py
from __future__ import annotations

"""
API-Sports odds + endpoint spec used by our normalizers and routers.

Exports
-------
MAP                : fast path id→alias/periods map (per league)
NAME_FALLBACKS     : resilient market-name classifiers (alias inference)
PERIOD_HINTS       : period inference from market/group names
APISPORTS_SPEC     : minimal op schema we call per league family
"""

__all__ = ["MAP", "NAME_FALLBACKS", "PERIOD_HINTS", "APISPORTS_SPEC"]

# =========================
# FAST PATH: id-based map
# =========================
# Keys kept as strings to avoid int/str mismatches from JSON.
MAP: dict[str, dict] = {
    "nfl": {
        "bets": {
            # Moneyline
            "1": {"alias": "moneyline", "periods": ["game"]},

            # Spread / Handicap
            "2":  {"alias": "spread", "periods": ["game", "1h", "2h"]},
            "47": {"alias": "spread", "periods": ["1q"]},
            "48": {"alias": "spread", "periods": ["2q"]},
            "49": {"alias": "spread", "periods": ["3q"]},
            "50": {"alias": "spread", "periods": ["4q"]},
            "51": {"alias": "spread", "periods": ["1h"]},
            "52": {"alias": "spread", "periods": ["2h"]},

            # Totals (Over/Under)
            "3":  {"alias": "total", "periods": ["game", "1h", "2h"]},
            "61": {"alias": "total", "periods": ["1q"]},
            "62": {"alias": "total", "periods": ["2q"]},
            "63": {"alias": "total", "periods": ["3q"]},
            "64": {"alias": "total", "periods": ["4q"]},
            "65": {"alias": "total", "periods": ["1h"]},
            "66": {"alias": "total", "periods": ["2h"]},
        }
    },
    "ncaaf": {
        "bets": {
            "1":  {"alias": "moneyline", "periods": ["game"]},
            "2":  {"alias": "spread",    "periods": ["game", "1h", "2h"]},
            "47": {"alias": "spread",    "periods": ["1q"]},
            "48": {"alias": "spread",    "periods": ["2q"]},
            "49": {"alias": "spread",    "periods": ["3q"]},
            "50": {"alias": "spread",    "periods": ["4q"]},
            "3":  {"alias": "total",     "periods": ["game", "1h", "2h"]},
            "61": {"alias": "total",     "periods": ["1q"]},
            "62": {"alias": "total",     "periods": ["2q"]},
            "63": {"alias": "total",     "periods": ["3q"]},
            "64": {"alias": "total",     "periods": ["4q"]},
        }
    },
    "nba": {
        "bets": {
            "1":  {"alias": "moneyline", "periods": ["game"]},
            "2":  {"alias": "spread",    "periods": ["game", "1h", "2h"]},
            "47": {"alias": "spread",    "periods": ["1q"]},
            "48": {"alias": "spread",    "periods": ["2q"]},
            "49": {"alias": "spread",    "periods": ["3q"]},
            "50": {"alias": "spread",    "periods": ["4q"]},
            "3":  {"alias": "total",     "periods": ["game", "1h", "2h"]},
            "61": {"alias": "total",     "periods": ["1q"]},
            "62": {"alias": "total",     "periods": ["2q"]},
            "63": {"alias": "total",     "periods": ["3q"]},
            "64": {"alias": "total",     "periods": ["4q"]},
        }
    },
    "ncaab": {
        "bets": {
            "1": {"alias": "moneyline", "periods": ["game"]},
            "2": {"alias": "spread",    "periods": ["game", "1h", "2h"]},
            "3": {"alias": "total",     "periods": ["game", "1h", "2h"]},
        }
    },
    "soccer": {
        "bets": {
            "1": {"alias": "moneyline", "periods": ["game"]},  # 1X2 FT
            "2": {"alias": "spread",    "periods": ["game"]},  # Asian Handicap
            "3": {"alias": "total",     "periods": ["game"]},  # O/U goals
        }
    },
}

# ======================================
# SAFE PATH: name fallbacks + period hints
# ======================================
NAME_FALLBACKS: dict[str, list[str]] = {
    "moneyline": ["moneyline", "ml", "1x2", "winner", "match odds", "match result"],
    "spread":    ["spread", "handicap", "asian handicap", "line handicap", "point spread", "run line", "goal line"],
    "total":     ["total", "over/under", "o/u", "totals", "points total", "game total", "goals over/under"],
}

PERIOD_HINTS: dict[str, list[str]] = {
    "1q":   ["1st quarter", "1q", "first quarter"],
    "2q":   ["2nd quarter", "2q", "second quarter"],
    "3q":   ["3rd quarter", "3q", "third quarter"],
    "4q":   ["4th quarter", "4q", "fourth quarter"],
    "1h":   ["1st half", "1h", "first half"],
    "2h":   ["2nd half", "2h", "second half"],
    "game": ["full game", "full time", "match", "regular time", "ft", "game", "all quarters", "90 minutes"],
}

# ======================================
# Minimal operation schema per family
# ======================================
APISPORTS_SPEC = {
    "nfl": {
        "base": "https://v1.american-football.api-sports.io",
        "ops": {
            "fixtures_by_date": {"path": "/games", "required": ["date"], "optional": ["league"]},
            "fixtures_range":   {"path": "/games", "required": ["from", "to"], "optional": ["league"]},
            "odds":             {"path": "/odds",  "required": ["game"], "optional": ["bookmaker", "bet"]},
            "injuries":         {"path": "/injuries", "required": [], "optional": ["team", "player"]},
        },
    },
    "ncaaf": {
        "base": "https://v1.american-football.api-sports.io",
        "ops": {
            "fixtures_by_date": {"path": "/games", "required": ["date"], "optional": ["league", "season"]},
            "fixtures_range":   {"path": "/games", "required": ["from", "to"], "optional": ["league", "season"]},
            "odds":             {"path": "/odds",  "required": ["game"], "optional": ["bookmaker", "bet"]},
            "injuries":         {"path": "/injuries", "required": [], "optional": ["team", "player"]},
        },
    },
    "nba": {
        "base": "https://v1.basketball.api-sports.io",
        "ops": {
            "fixtures_by_date": {"path": "/games", "required": ["date"], "optional": ["league", "season"]},
            "fixtures_range":   {"path": "/games", "required": ["from", "to"], "optional": ["league", "season"]},
            "odds":             {"path": "/odds",  "required": ["game"], "optional": ["bookmaker", "bet"]},
            # injuries: not provided by API-Sports
        },
    },
    "ncaab": {
        "base": "https://v1.basketball.api-sports.io",
        "ops": {
            "fixtures_by_date": {"path": "/games", "required": ["date"], "optional": ["league", "season"]},
            "fixtures_range":   {"path": "/games", "required": ["from", "to"], "optional": ["league", "season"]},
            "odds":             {"path": "/odds",  "required": ["game"], "optional": ["bookmaker", "bet"]},
            # injuries: not provided by API-Sports
        },
    },
    "soccer": {
        "base": "https://v3.football.api-sports.io",
        "ops": {
            "fixtures_by_date": {"path": "/fixtures", "required": ["date"], "optional": ["league", "season", "team", "timezone"]},
            "fixtures_range":   {"path": "/fixtures", "required": ["from", "to"], "optional": ["league", "season", "team", "timezone"]},
            "odds":             {"path": "/odds",     "required": ["fixture"], "optional": ["bookmaker", "bet"]},
            "injuries":         {"path": "/injuries", "required": ["league", "season"], "optional": ["team", "player"]},
        },
    },
}
