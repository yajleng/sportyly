# app/services/validation.py
from __future__ import annotations

from typing import Dict, Iterable, Optional, Set, Tuple
from fastapi import HTTPException

# Leagues your app currently supports everywhere
ACCEPTED_LEAGUES: Set[str] = {"nba", "nfl", "ncaaf", "ncaab", "soccer"}

# For each (league, operation) pair, list the **provider-facing** params
# we purposely allow to pass through. Everything else should be rejected.
# Only include keys you actually forward to the API-SPORTS client.
_ALLOWED: Dict[Tuple[str, str], Set[str]] = {
    # -------- injuries --------
    ("nfl", "injuries"): {"team", "player"},
    ("ncaaf", "injuries"): {"team", "player"},
    ("soccer", "injuries"): {"league", "season", "team", "player"},
    # nba/ncaab: not supported by provider — handled in the route

    # -------- odds --------
    # In routes we forward ONLY bookmaker → "bookmaker" and bet → "bet"
    ("nfl", "odds"): {"bookmaker", "bet"},
    ("ncaaf", "odds"): {"bookmaker", "bet"},
    ("soccer", "odds"): {"bookmaker", "bet"},

    # (Optional) add more when you start passing extra filters
    # ("soccer","fixtures"): {"date","from","to","league","season","team"},
}

def _fmt_expected() -> str:
    return ", ".join(sorted(ACCEPTED_LEAGUES))

def validate_league(league: str) -> None:
    """
    Ensure the league value matches one of your supported literals exactly.
    This gives a clean 422 even if a caller bypasses Pydantic's Literal.
    """
    if league not in ACCEPTED_LEAGUES:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid league", "input": league, "expected": sorted(ACCEPTED_LEAGUES)},
        )

def reject_unknown_params(league: str, operation: str, provider_params: Dict[str, object]) -> None:
    """
    For a given (league, operation) allow only a small, explicit set of
    provider-facing keys to pass downstream. Everything else is rejected early.
    """
    allowed = _ALLOWED.get((league, operation), set())
    unknown = set(provider_params.keys()) - allowed
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Unknown query parameter(s) for operation",
                "operation": operation,
                "league": league,
                "unknown": sorted(unknown),
                "allowed": sorted(allowed),
            },
        )

def ensure_required_params(required_keys: Iterable[str], provider_params: Dict[str, Optional[object]]) -> None:
    """
    Ensure all required keys are present and truthy in provider_params.
    (Used for cases like soccer injuries which require league+season.)
    """
    missing = [k for k in required_keys if not provider_params.get(k)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "Missing required parameter(s)", "missing": sorted(missing)},
        )
