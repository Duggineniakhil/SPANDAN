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

    # Approval engine: how often to send 24 h reminders / expire 48 h-old plans (0 = off)
    approval_sweep_interval_s: float = 300

    # Diagnosis + RUL (M2-26). Paths are relative to backend/; the files come from the ML runs.
    # The model file is a pickle: only ever point this at our own trained artifact.
    diagnosis_model_path: str = "../ml/results/diagnosis-hgb-v1.joblib"
    rul_config_path: str = "../ml/results/rul_config_v1.json"
    default_repair_days: float = 3.0   # repair deadline when RUL has no trend yet (conservative)
    reading_interval_min: float = 1.0  # one reading per minute on the phone (the web demo runs faster)
    raw_windows_keep: int = 12         # raw windows kept per machine and kind

    # Voice (M2-27 – M2-31): Gnani TTS for the plan's voice note, STT for the owner's spoken reply.
    # No key = no voice; the owner reads the text and taps Approve/Reject.
    gnani_api_key: str = ""
    gnani_tts_url: str = "https://api.vachana.ai/api/v1/tts/inference"
    gnani_stt_url: str = "https://api.vachana.ai/stt/v3"
    gnani_tts_model: str = "timbre-v3.0"
    gnani_stt_model: str = "prisma-v3.0"
    # v3.0 voices speak every language; these sounded clear in our Kannada/Hindi tests
    gnani_voice_kn: str = "Shruthi"
    gnani_voice_hi: str = "Shivani"
    gnani_voice_en: str = "Shruthi"
    voice_timeout_s: float = 20       # per Gnani call; on timeout the owner gets text + buttons
    voice_dir: str = "var/voice"      # generated notes and recorded replies (relative to backend/)
    voice_max_reply_bytes: int = 5_000_000
    voice_max_reply_s: float = 30     # Gnani STT limit
    voice_reask_max: int = 2          # unclear replies re-asked this many times, then tap buttons
    ffmpeg_path: str = "ffmpeg"

    # Anomaly rule on the server (backup for the phone's own alert)
    server_alert_consecutive: int = 3

    # Telemetry acceptance window
    max_future_skew_minutes: int = 10
    max_row_age_days: int = 60
    max_rows_per_batch: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
