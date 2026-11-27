from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://spandan:spandan@localhost:5433/spandan"
    test_database_url: str = "postgresql+psycopg://spandan:spandan@localhost:5433/spandan_test"
    api_token: str = "change-me"

    # LLMs for the coordinator agent, tried in this order; the next one takes over on any failure.
    # Groq first: in live tests it wrote correct Kannada/Hindi script, while Gemini flash was
    # overloaded (503) and flash-lite wrote Kannada in English letters.
    agent_providers: str = "groq,gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"  # flash models were overloaded (503) on the free tier
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    agent_auto_plan: bool = True  # plan automatically when an anomaly event is diagnosed
    agent_max_tool_calls: int = 12
    agent_timeout_s: int = 90
    llm_request_timeout_s: float = 30  # per model call; a hung provider falls back instead of blocking

    # Anomaly rule on the server (backup for the phone's own alert)
    server_alert_consecutive: int = 3

    # Telemetry acceptance window
    max_future_skew_minutes: int = 10
    max_row_age_days: int = 60
    max_rows_per_batch: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
