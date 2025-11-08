
from .core.config import get_settings
from .clients.apisports import ApiSportsClient

def get_client() -> ApiSportsClient:
    s = get_settings()
    return ApiSportsClient(api_key=s.apisports_key)
