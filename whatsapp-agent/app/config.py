from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    meta_verify_token: str = Field(default="", alias="META_VERIFY_TOKEN")
    meta_access_token: str = Field(default="", alias="META_ACCESS_TOKEN")
    meta_phone_number_id: str = Field(default="", alias="META_PHONE_NUMBER_ID")
    meta_graph_version: str = Field(default="v23.0", alias="META_GRAPH_VERSION")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field(default="claude-sonnet-4-5", alias="CLAUDE_MODEL")

    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    database_path: Path = Field(default=Path("/tmp/agent.sqlite3"), alias="DATABASE_PATH")
    upload_dir: Path = Field(default=Path("/tmp/uploads"), alias="UPLOAD_DIR")
    output_dir: Path = Field(default=Path("/tmp/outputs"), alias="OUTPUT_DIR")
    knowledge_dir: Path = Field(default=Path("./knowledge"), alias="KNOWLEDGE_DIR")
    max_history_messages: int = Field(default=12, alias="MAX_HISTORY_MESSAGES")
    aggie_private_profile: str = Field(default="", alias="AGGIE_PRIVATE_PROFILE")
    kv_rest_api_url: str = Field(default="", alias="KV_REST_API_URL")
    kv_rest_api_token: str = Field(default="", alias="KV_REST_API_TOKEN")
    upstash_redis_rest_url: str = Field(default="", alias="UPSTASH_REDIS_REST_URL")
    upstash_redis_rest_token: str = Field(default="", alias="UPSTASH_REDIS_REST_TOKEN")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if os.environ.get("VERCEL"):
        settings.database_path = _vercel_safe_path(settings.database_path, "agent.sqlite3")
        settings.upload_dir = _vercel_safe_path(settings.upload_dir, "uploads")
        settings.output_dir = _vercel_safe_path(settings.output_dir, "outputs")
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    return settings


def _vercel_safe_path(path: Path, fallback_name: str) -> Path:
    if str(path).startswith("/tmp/"):
        return path
    return Path("/tmp") / fallback_name
