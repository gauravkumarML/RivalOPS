from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/rivalops"
    )
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model_fast: str = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")
    openai_model_smart: str = os.getenv("OPENAI_MODEL_SMART", "gpt-4o")
    firecrawl_api_key: str | None = os.getenv("FIRECRAWL_API_KEY")
    slack_webhook_url: str | None = os.getenv("SLACK_WEBHOOK_URL")
    base_url: str = os.getenv("RIVALOPS_BASE_URL", "http://localhost:8000")


settings = Settings()

