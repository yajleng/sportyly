# app/main.py
from fastapi import FastAPI
from .routers import health, picks, backtest, data

app = FastAPI(title="GPT Picks API", version="0.1.0")

# Routers
app.include_router(health.router)
app.include_router(picks.router)
app.include_router(backtest.router)
app.include_router(data.router)

@app.get("/")
def root():
    return {"service": "gpt-picks-api"}
