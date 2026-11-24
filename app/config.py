"""Settings read from environment variables (never hard-coded secrets)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./agent.db")

    # LLM
    llm_mode: str = os.getenv("LLM_MODE", "anthropic")  # "anthropic" or "fake" (offline backup)
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    max_agent_steps: int = int(os.getenv("MAX_AGENT_STEPS", "8"))  # per visitor message
    max_visitor_messages: int = int(os.getenv("MAX_VISITOR_MESSAGES", "30"))  # per conversation

    # Admin view (/admin). Empty = open (fine on your own laptop, not on the internet).
    admin_token: str = os.getenv("ADMIN_TOKEN", "")


settings = Settings()
