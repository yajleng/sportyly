from fastapi import APIRouter, HTTPException, Query
from ..clients.apisports import ApiSportsClient, League
from ..core.config import get_settings

router = APIRouter(prefix="/data/debug", tags=["debug"])

def _client() -> ApiSportsClient:
    return ApiSportsClient(api_key=get_settings().apisports_key)

@router.get("/bookmakers", summary="List bookmakers present for a fixture")
def bookmakers(league: League, fixture_id: int = Query(..., description="Game/fixture id")):
    c = _client()
    try:
        raw = c.odds_for_fixture(league, fixture_id)
    finally:
        c.close()
    books = (raw or {}).get("response", [])
    if not books:
        return {"fixture_id": fixture_id, "bookmakers": []}
    out = [{"id": b.get("id"), "name": b.get("name")} for b in books[0].get("bookmakers", [])]
    return {"fixture_id": fixture_id, "bookmakers": out}

@router.get("/markets", summary="List markets (bets) available for a fixture & bookmaker")
def markets(league: League, fixture_id: int, bookmaker_id: int):
    c = _client()
    try:
        raw = c.odds_for_fixture(league, fixture_id)
    finally:
        c.close()
    resp = (raw or {}).get("response", [])
    if not resp:
        return {"fixture_id": fixture_id, "bookmaker_id": bookmaker_id, "bets": []}
    for bk in resp[0].get("bookmakers", []):
        if bk.get("id") == bookmaker_id:
            bets = [{"id": b.get("id"), "name": b.get("name")} for b in bk.get("bets", [])]
            return {"fixture_id": fixture_id, "bookmaker_id": bookmaker_id, "bets": bets}
    return {"fixture_id": fixture_id, "bookmaker_id": bookmaker_id, "bets": []}
