from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List

class Settings(BaseSettings):
    app_name: str = Field(default="RenderFastAPI", alias="APP_NAME")
    app_env: str = Field(default="production", alias="APP_ENV")
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], alias="CORS_ORIGINS")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }

settings = Settings()


from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    app_name: str = Field(default="RenderFastAPI", alias="APP_NAME")
    app_env: str = Field(default="production", alias="APP_ENV")
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], alias="CORS_ORIGINS")
    api_keys: List[str] = Field(default_factory=list, alias="API_KEYS")

    sports_provider: str = Field(default="mock", alias="SPORTS_PROVIDER")
    sports_api_key: Optional[str] = Field(default=None, alias="APISPORTS_KEY")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }

settings = Settings()
