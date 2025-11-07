# RenderFastAPI backend (essentials)


A minimal FastAPI backend ready for local development. We'll add Render deployment and custom GPT API endpoints in subsequent steps.


## Quickstart


### 1) Setup


```bash
python -m venv .venv
source .venv/bin/activate # Windows: .venv\\Scripts\\activate
pip install -U pip
pip install -e .[dev]
cp .env.example .env
