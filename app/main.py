from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.logging import configure_logging

# Required routers
from app.api.v1.endpoints import ping as ping_endpoint
from app.api.v1.endpoints import vendor as vendor_endpoint

# Optional routers (import if present)
try:
    from app.api.v1.endpoints import markets as markets_endpoint
except Exception:
    markets_endpoint = None

try:
    from app.api.v1.endpoints import gpt as gpt_endpoint
except Exception:
    gpt_endpoint = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield

app = FastAPI(title=settings.app_name, lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root
@app.get("/", include_in_schema=False)
async def root():
    return {"app": settings.app_name, "env": settings.app_env}

# Versioned API router
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(ping_endpoint.router)
api_v1.include_router(vendor_endpoint.router)
if markets_endpoint:
    api_v1.include_router(markets_endpoint.router)
if gpt_endpoint:
    api_v1.include_router(gpt_endpoint.router)

# Mount
app.include_router(api_v1)
