# app/deps.py
from fastapi import Depends
from app.core.config import settings

def get_provider():
    """
    Returns the active sports data provider.
    - If SPORTS_PROVIDER=apisports and APISPORTS_KEY is set -> ApiSportsProvider
    - Otherwise -> MockSportsProvider
    Lazy imports keep the app bootable even if vendor modules are missing.
    """
    if settings.sports_provider == "apisports" and settings.sports_api_key:
        from app.providers.apisports import ApiSportsProvider
        return ApiSportsProvider(settings.sports_api_key)
    else:
        from app.providers.mock import MockSportsProvider
        return MockSportsProvider()

def provider_dep(p = Depends(get_provider)):
    return p
