from fastapi import Depends
from app.core.config import settings
from app.providers.apisports import ApiSportsProvider
from app.providers.mock import MockSportsProvider  # keep your mock from earlier

def get_provider():
    if settings.sports_provider == "apisports" and settings.sports_api_key:
        return ApiSportsProvider(settings.sports_api_key)
    return MockSportsProvider()

def provider_dep(p = Depends(get_provider)):
    return p
