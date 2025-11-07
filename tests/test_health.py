import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_ping():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/api/v1/ping")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
