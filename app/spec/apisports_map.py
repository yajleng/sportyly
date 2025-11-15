# app/spec/apisports_map.py
from __future__ import annotations

# Public export surface
__all__ = ["MAP", "APISPORTS_SPEC"]

# -----------------------------------------------------------------------------
# Alias → bet_id mapping (stub values). Replace string keys with real API-Sports
# bet IDs per league when you have them. The app can run without these being
# perfect; they’re only used when you want to resolve aliases -> bet filter.
# -----------------------------------------------------------------------------
MAP = {
    "nfl": {
        "bets": {
            "1": {"alias": "moneyline", "periods": ["game"]},
            "2": {"alias": "spread",    "periods": ["game", "1h", "2h"]},
            "3": {"alias": "total",     "periods": ["game", "1h", "2h"]},
        }
    },
    "ncaaf": {
        "bets": {
            "1": {"alias": "moneyline", "periods": ["game"]},
            "2": {"alias": "spread",    "periods": ["game"]},
            "3": {"alias": "total",     "periods": ["game"]},
        }
    },
    "nba": {
        "bets": {
            "1": {"alias": "moneyline", "periods": ["game"]},
            "2": {"alias": "spread",    "periods": ["game", "1h"]},
            "3": {"alias": "total",     "periods": ["game", "1h"]},
        }
    },
    "ncaab": {
        "bets": {
            "1": {"alias": "moneyline", "periods": ["game"]},
            "2": {"alias": "spread",    "periods": ["game"]},
            "3": {"alias": "total",     "periods": ["game"]},
        }
    },
    "soccer": {
        "bets": {
            "1": {"alias": "moneyline", "periods": ["game"]},   # 1X2 in practice
            "2": {"alias": "spread",    "periods": ["game"]},   # Asian handicap
            "3": {"alias": "total",     "periods": ["game"]},   # Over/Under
        }
    },
}

# -----------------------------------------------------------------------------
# Minimal operation schema we actually call per league family.
# This is informational/validation-only; clients build URLs elsewhere.
# -----------------------------------------------------------------------------
APISPORTS_SPEC = {
    "nfl": {
        "base": "https://v1.american-football.api-sports.io",
        "ops": {
            "fixtures_by_date": {
                "path": "/games",
                "required": ["date"],          # YYYY-MM-DD
                "optional": ["league"],        # typically implied by base + headers
            },
            "fixtures_range": {
                "path": "/games",
                "required": ["from", "to"],
                "optional": ["league"],
            },
            "odds": {
                "path": "/odds",
                "required": ["game"],          # game id
                "optional": ["bookmaker", "bet"],
            },
            "injuries": {
                "path": "/injuries",
                "required": [],                # router enforces team/player presence
                "optional": ["team", "player"],
            },
        },
    },
    "ncaaf": {
        "base": "https://v1.american-football.api-sports.io",
        "ops": {
            "fixtures_by_date": {
                "path": "/games",
                "required": ["date"],
                "optional": ["league", "season"],
            },
            "fixtures_range": {
                "path": "/games",
                "required": ["from", "to"],
                "optional": ["league", "season"],
            },
            "odds": {
                "path": "/odds",
                "required": ["game"],
                "optional": ["bookmaker", "bet"],
            },
            "injuries": {
                "path": "/injuries",
                "required": [],
                "optional": ["team", "player"],
            },
        },
    },
    "nba": {
        "base": "https://v1.basketball.api-sports.io",
        "ops": {
            "fixtures_by_date": {
                "path": "/games",
                "required": ["date"],
                "optional": ["league", "season"],
            },
            "fixtures_range": {
                "path": "/games",
                "required": ["from", "to"],
                "optional": ["league", "season"],
            },
            "odds": {
                "path": "/odds",
                "required": ["game"],
                "optional": ["bookmaker", "bet"],
            },
            # injuries not provided for NBA by API-Sports
        },
    },
    "ncaab": {
        "base": "https://v1.basketball.api-sports.io",
        "ops": {
            "fixtures_by_date": {
                "path": "/games",
                "required": ["date"],
                "optional": ["league", "season"],
            },
            "fixtures_range": {
                "path": "/games",
                "required": ["from", "to"],
                "optional": ["league", "season"],
            },
            "odds": {
                "path": "/odds",
                "required": ["game"],
                "optional": ["bookmaker", "bet"],
            },
            # injuries not provided for NCAAB by API-Sports
        },
    },
    "soccer": {
        "base": "https://v3.football.api-sports.io",
        "ops": {
            "fixtures_by_date": {
                "path": "/fixtures",
                "required": ["date"],
                "optional": ["league", "season", "team", "timezone"],
            },
            "fixtures_range": {
                "path": "/fixtures",
                "required": ["from", "to"],
                "optional": ["league", "season", "team", "timezone"],
            },
            "odds": {
                "path": "/odds",
                "required": ["fixture"],       # fixture id
                "optional": ["bookmaker", "bet"],
            },
            "injuries": {
                "path": "/injuries",
                "required": ["league", "season"],
                "optional": ["team", "player"],
            },
        },
    },
}
