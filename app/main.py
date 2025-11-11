from fastapi import FastAPI
from .routers import health, picks, backtest

app = FastAPI(title="GPT Picks API", version="0.1.0")
app.include_router(health.router)   # no prefix
app.include_router(picks.router)
app.include_router(backtest.router)

@app.get("/")
def root():
    return {"service": "gpt-picks-api"}
