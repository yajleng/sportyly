from fastapi import APIRouter, Response

router = APIRouter(tags=["health"])

@router.get("/api/v1/ping")
def ping():
    return {"pong": True}

@router.get("/health")
def health():
    return {"status": "ok"}

@router.head("/")
def head_root():
    return Response(status_code=200)
