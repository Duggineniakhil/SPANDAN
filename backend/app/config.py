from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://spandan:spandan@localhost:5433/spandan"
    test_database_url: str = "postgresql+psycopg://spandan:spandan@localhost:5433/spandan_test"
    api_token: str = "change-me"

    # Telemetry acceptance window
    max_future_skew_minutes: int = 10
    max_row_age_days: int = 60
    max_rows_per_batch: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
