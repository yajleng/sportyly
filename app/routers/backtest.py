
from fastapi import APIRouter, Depends, Query
from ..clients.apisports import ApiSportsClient, League
from ..deps import get_client
from ..services.picks import build_picks

router = APIRouter(prefix="/backtest", tags=["backtest"])

@router.get("")
def backtest(
    league: League,
    start_date: str,
    end_date: str,
    season: int | None = None,
    client: ApiSportsClient = Depends(get_client),
):
    # Very naive example: sum expected value of ML picks over date range
    # Replace with proper bankroll Kelly/flat staking and realized results once odds+scores are mapped.
    from datetime import date, timedelta
    import json

    def d(s): return date.fromisoformat(s)
    cur = d(start_date)
    ev = 0.0
    picks_count = 0

    while cur <= d(end_date):
        day = cur.isoformat()
        ps = build_picks(client, league, day, season, bet_types=["moneyline"], league_id_override=None)
        for p in ps:
            # EV per $1 stake at offered price (placeholder)
            implied = 0.0 if p.price is None else (100/(p.price+100) if p.price>0 else (-p.price)/(-p.price+100))
            edge = p.win_prob - implied
            ev += edge
            picks_count += 1
        cur += timedelta(days=1)

    return {"picks": picks_count, "sum_ev": ev}
