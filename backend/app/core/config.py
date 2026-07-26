from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://infraos:infraos@localhost:2001/infraos"
    redis_url: str = "redis://localhost:2002/0"

    # Fernet key for encrypting device credentials at rest
    credentials_encryption_key: str = ""

    metrics_poll_interval_seconds: int = 30
    digital_twin_cache_ttl_seconds: int = 20

    # CORS
    cors_origins: List[str] = ["http://localhost:2020"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value):
        if value is None:
            return ["http://localhost:2020"]

        if isinstance(value, list):
            return value

        if isinstance(value, str):
            value = value.strip()

            # JSON array
            if value.startswith("["):
                import json
                return json.loads(value)

            # Comma-separated list
            return [origin.strip() for origin in value.split(",") if origin.strip()]

        return value

    # Secrets backend
    secrets_backend: str = "fernet"
    vault_addr: str = ""
    vault_token: str = ""
    vault_mount_point: str = "secret"

    # JWT
    jwt_secret_key: str = ""
    jwt_expiry_minutes: int = 480

    # Bootstrap admin
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "change-me-immediately"


@lru_cache
def get_settings() -> Settings:
    return Settings()
