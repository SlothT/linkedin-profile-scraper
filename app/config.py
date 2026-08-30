from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    linkedin_li_at: str | None = Field(default=None, repr=False)
    api_key: str | None = Field(default=None, repr=False)
    proxy_url: str | None = None
    ca_bundle: str | None = None
    cache_ttl: int = 900
    upstream_limit: int = 8
    rate_limit_per_minute: int = 30
    example_fixture_path: str = "fixtures/profile_sample.json"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
