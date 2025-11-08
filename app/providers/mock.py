from datetime import datetime, timedelta, timezone
from app.domain.models import Game, Team, Price, Line, MarketBook, League

class MockSportsProvider:
    """
    Simple in-memory provider returning a single mock game with a few lines.
    Returns a plain list[MarketBook] so callers can `await provider.list_games(...)`
    without using `async for`.
    """
    async def list_games(self, league: League) -> list[MarketBook]:
        now = datetime.now(timezone.utc)
        gid = "mock-1"

        game = Game(
            game_id=gid,
            league=league,
            start_iso=(now + timedelta(hours=3)).isoformat(),
            home=Team(id=f"{gid}-H", name="Home Team", abbr="HOM"),
            away=Team(id=f"{gid}-A", name="Away Team", abbr="AWY"),
        )

        lines = [
            Line(market="spread", team_side="home", point=-3.5, prices=[Price(bookmaker="mock", price=1.91)]),
            Line(market="spread", team_side="away", point=+3.5, prices=[Price(bookmaker="mock", price=1.91)]),
            Line(market="total", point=221.5, prices=[Price(bookmaker="mock", price=1.91)]),
            Line(market="moneyline", team_side="home", prices=[Price(bookmaker="mock", price=1.80)]),
            Line(market="moneyline", team_side="away", prices=[Price(bookmaker="mock", price=2.05)]),
        ]

        return [MarketBook(game=game, lines=lines)]
