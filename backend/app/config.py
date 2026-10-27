import base64
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANA_", env_file=ROOT / ".env", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://sana:sana_local_only@127.0.0.1:5432/sana"
    )
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    allowed_origins: list[str] = ["http://127.0.0.1:8000", "http://127.0.0.1:4173"]
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    auth_mode: Literal["jwks", "auth_server"] = "jwks"
    google_oauth_enabled: bool = False
    jwt_audience: str = "authenticated"
    storage_dir: Path = ROOT / ".data/assets"
    model_cache_dir: Path = ROOT / ".data/models"
    image_model_id: str = "stable-diffusion-v1-5/stable-diffusion-v1-5"
    image_variant: str = "fp16"
    image_device: Literal["auto", "cpu", "mps", "cuda"] = "auto"
    image_enabled: bool = False
    image_steps: int = Field(20, ge=1, le=80)
    image_size: int = Field(512, ge=256, le=1024, multiple_of=64)
    image_max_count: int = Field(4, ge=1, le=8)
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: int = Field(180, ge=10, le=1800)
    llm_context_characters: int = Field(24000, ge=1000, le=100000)
    llm_max_tokens: int = Field(4096, ge=256, le=16384)
    llm_reasoning_effort: Literal["", "none", "low", "medium", "high"] = "none"
    llm_response_format: Literal["json_schema", "json_object"] = "json_schema"
    max_request_bytes: int = Field(65536, ge=1024, le=1048576)
    max_result_bytes: int = Field(131072, ge=1024, le=1048576)
    max_active_jobs: int = Field(2, ge=1, le=10)
    job_timeout_seconds: int = Field(900, ge=60, le=7200)
    queue_timeout_seconds: int = Field(3600, ge=60, le=86400)
    costs: dict[str, int] = {"lesson": 10, "quiz": 6, "flashcards": 6, "comic": 12, "image": 10}
    plan_config_path: Path = ROOT / "config/plans.json"

    @model_validator(mode="after")
    def validate_configuration(self):
        self.supabase_url = self.supabase_url.rstrip("/")
        if self.supabase_url and not self.supabase_url.startswith("https://"):
            if self.environment == "production" or not self.supabase_url.startswith(
                ("http://127.0.0.1:", "http://localhost:")
            ):
                raise ValueError("Supabase requires HTTPS (loopback allowed in development)")
        if self.supabase_publishable_key.startswith("sb_secret_"):
            raise ValueError("Use a Supabase publishable key, never a secret key")
        key = self.supabase_publishable_key
        if key and not key.startswith("sb_publishable_"):
            try:
                payload = key.split(".")[1]
                role = json.loads(
                    base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
                ).get("role")
                if role != "anon":
                    raise ValueError("Only a legacy anon key is safe for the browser")
            except (IndexError, ValueError, TypeError) as error:
                raise ValueError(
                    "Use a publishable key or legacy anon key, never service_role"
                ) from error
        if set(self.costs) != {"lesson", "quiz", "flashcards", "comic", "image"}:
            raise ValueError("Configure all five operation costs")
        if any(type(value) is not int or value <= 0 for value in self.costs.values()):
            raise ValueError("Operation costs must be positive integers")
        if self.environment == "production" and not self.auth_configured:
            raise ValueError("Configure Supabase URL and publishable key for production")
        return self

    @property
    def auth_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
