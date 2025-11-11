from fastapi import APIRouter, Response

# No prefix so /api/v1/ping is the real path.
router = APIRouter(tags=["health"])

@router.get("/api/v1/ping")
def ping():
    return {"pong": True}

@router.get("/health")
def health():
    return {"status": "ok"}

# Some platforms probe HEAD /
@router.head("/")
def head_root():
    return Response(status_code=200)
