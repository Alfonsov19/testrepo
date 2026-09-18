"""Configuration, read once from the process environment.

Secrets are never logged or returned by the API.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    jev_model: str
    claude_model: str
    typesafe_base_url: str
    typesafe_api_key: str | None
    anthropic_api_key: str | None
    db_path: str
    signal_threshold: float

    @property
    def jev_available(self) -> bool:
        return bool(self.typesafe_api_key)

    @property
    def claude_available(self) -> bool:
        return bool(self.anthropic_api_key)


def load_settings() -> Settings:
    return Settings(
        jev_model=os.getenv("JEV_MODEL", "jev-1.13.0"),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-opus-5"),
        typesafe_base_url=os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai"),
        typesafe_api_key=os.getenv("TYPESAFE_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        db_path=os.getenv("CRM_DB_PATH", "./crm.db"),
        signal_threshold=float(os.getenv("SIGNAL_THRESHOLD", "0.50")),
    )


SETTINGS = load_settings()
