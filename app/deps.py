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

from fastapi import Depends
from app.core.config import settings

def get_provider():
    if settings.sports_provider == "apisports" and settings.sports_api_key:
        # Lazy import so the app can still boot without vendor files during dev
        from app.providers.apisports import ApiSportsProvider
        return ApiSportsProvider(settings.sports_api_key)
    else:
        from app.providers.mock import MockSportsProvider
        return MockSportsProvider()

def provider_dep(p = Depends(get_provider)):
    return p
