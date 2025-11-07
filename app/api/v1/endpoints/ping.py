
from fastapi import APIRouter

router = APIRouter()

@router.get("/ping", summary="Healthcheck / ping")
async def ping():
    return {"status": "ok"}
