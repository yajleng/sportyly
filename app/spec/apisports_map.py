# app/spec/apisports_map.py
from __future__ import annotations

# Minimal, high-signal contract for the operations we actually call.
# Each op defines which params are required/optional for each league.
APISPORTS_SPEC = {
    "nfl": {
        "base": "https://v1.american-football.api-sports.io",
        "ops": {
            "fixtures_by_date": {
                "path": "/games",
                "required": ["date"],   # YYYY-MM-DD (provider local rules)
                "optional": [],
            },
            "fixtures_range": {
                "path": "/games",
                "required": ["from", "to"],
                "optional": [],
            },
            "odds": {
                "path": "/odds",
                "required": ["game"],   # provider expects 'game' (id)
                "optional": ["bookmaker", "bet"],
            },
            "injuries": {
                "path": "/injuries",
                "required": [],         # must have at least one of team/player in our router
                "optional": ["team", "player"],
            },
        },
    },
    "ncaaf": {
        "base": "https://v1.american-football.api-sports.io",
        "ops": {
            "fixtures_by_date": {"path": "/games", "required": ["date"], "optional": ["season"]},
            "fixtures_range":   {"path": "/games", "required": ["from", "to"], "optional": ["season"]},
            "odds":             {"path": "/odds",  "required": ["game"], "optional": ["bookmaker", "bet"]},
            "injuries":         {"path": "/injuries", "required": [], "optional": ["team", "player"]},
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
                "required": ["fixture"],
                "optional": ["bookmaker", "bet"],
            },
            "injuries": {
                "path": "/injuries",
                "required": ["league", "season"],   # per provider, league+season mandatory
                "optional": ["team", "player"],
            },
        },
    },
    # Add more leagues here as you turn them on.
}
