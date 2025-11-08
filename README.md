
# GPT Picks API (API-SPORTS + FastAPI)

ARender-ready backend that aggregates API-SPORTS data and produces probability-based picks for NBA, NFL, NCAAF, NCAAB, and Soccer.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add APISPORTS_KEY
uvicorn app.main:app --reload
