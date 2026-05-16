from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_MINERU_COMMAND = "mineru"
DEFAULT_OBJECT_STORAGE_BUCKET = "question-bank-assets"
DEFAULT_DATABASE_URL = "postgresql+psycopg://question_bank:question_bank@localhost:5432/question_bank"
DEFAULT_MINIO_ENDPOINT = "http://localhost:9000"
DEFAULT_MINIO_ACCESS_KEY = "questionbank"
DEFAULT_MINIO_SECRET_KEY = "questionbank123"


@dataclass(frozen=True, slots=True)
class Settings:
    deepseek_api_key: str | None = None
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    mineru_command: str = DEFAULT_MINERU_COMMAND
    object_storage_bucket: str = DEFAULT_OBJECT_STORAGE_BUCKET
    database_url: str = DEFAULT_DATABASE_URL
    minio_endpoint: str = DEFAULT_MINIO_ENDPOINT
    minio_access_key: str = DEFAULT_MINIO_ACCESS_KEY
    minio_secret_key: str = DEFAULT_MINIO_SECRET_KEY

    @classmethod
    def load(cls) -> "Settings":
        return cls.from_env(os.environ)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        return cls(
            deepseek_api_key=_blank_to_none(env.get("DEEPSEEK_API_KEY")),
            deepseek_base_url=env.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).rstrip("/"),
            deepseek_model=env.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
            mineru_command=env.get("MINERU_COMMAND", DEFAULT_MINERU_COMMAND),
            object_storage_bucket=env.get("OBJECT_STORAGE_BUCKET", DEFAULT_OBJECT_STORAGE_BUCKET),
            database_url=env.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            minio_endpoint=env.get("MINIO_ENDPOINT", DEFAULT_MINIO_ENDPOINT).rstrip("/"),
            minio_access_key=env.get("MINIO_ACCESS_KEY", DEFAULT_MINIO_ACCESS_KEY),
            minio_secret_key=env.get("MINIO_SECRET_KEY", DEFAULT_MINIO_SECRET_KEY),
        )


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value
