import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
ROOT_ENV_FILE = REPO_DIR / ".env"
BACKEND_ENV_FILE = BACKEND_DIR / ".env"
ENV_FILES = (ROOT_ENV_FILE,)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://reviewpulse:reviewpulse@localhost:5432/reviewpulse"
    )

    # ── Redis / Celery ────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Supabase ──────────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    # Used for local JWT validation — avoids a round-trip to Supabase on every request
    supabase_jwt_secret: str = ""
    use_supabase_admin_signup: bool = True

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "deepseek"  # "deepseek" | "anthropic"
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""

    # deepseek-embedding outputs 1024-dimensional vectors. This must match
    # the vector() column size in the Alembic migration — change both together.
    embedding_dim: int = 1024

    # ── LLM Pricing (per 1M tokens, USD) ──────────────────────────────────────
    # Prices from provider dashboards; update when rates change. We track cost
    # per review so authors can see exactly what analysis costs (N3).
    deepseek_input_price_per_million: float = 0.14
    deepseek_output_price_per_million: float = 0.28
    anthropic_input_price_per_million: float = 0.25   # claude-3-haiku
    anthropic_output_price_per_million: float = 1.25  # claude-3-haiku

    # ── App ───────────────────────────────────────────────────────────────────
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_token: str = "change-me-admin-token"

    # Reject webhook payloads older than this to prevent replay attacks (N10)
    webhook_replay_window_seconds: int = 300

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            return json.loads(raw)
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def _is_missing_or_placeholder(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    return (
        not stripped
        or "<" in stripped
        or lowered.startswith("your-")
        or "placeholder" in lowered
    )


def auth_config_issues() -> list[str]:
    issues: list[str] = []
    supabase_url = settings.supabase_url.strip()

    if _is_missing_or_placeholder(supabase_url):
        issues.append("SUPABASE_URL is missing or still a placeholder")
    elif not supabase_url.startswith(("http://", "https://")):
        issues.append("SUPABASE_URL must start with http:// or https://")

    if _is_missing_or_placeholder(settings.supabase_anon_key):
        issues.append("SUPABASE_ANON_KEY is missing or still a placeholder")

    if _is_missing_or_placeholder(settings.supabase_jwt_secret):
        issues.append("SUPABASE_JWT_SECRET is missing or still a placeholder")

    if settings.use_supabase_admin_signup and _is_missing_or_placeholder(
        settings.supabase_service_key
    ):
        issues.append(
            "SUPABASE_SERVICE_KEY is missing or still a placeholder "
            "while USE_SUPABASE_ADMIN_SIGNUP is true"
        )

    return issues


def llm_config_issues() -> list[str]:
    issues: list[str] = []

    if settings.llm_provider not in {"deepseek", "anthropic"}:
        issues.append("LLM_PROVIDER must be deepseek or anthropic")

    if _is_missing_or_placeholder(settings.deepseek_api_key):
        issues.append("DEEPSEEK_API_KEY is missing or still a placeholder")

    if settings.llm_provider == "anthropic" and _is_missing_or_placeholder(
        settings.anthropic_api_key
    ):
        issues.append("ANTHROPIC_API_KEY is missing or still a placeholder")

    return issues


def config_diagnostics() -> dict:
    auth_issues = auth_config_issues()
    llm_issues = llm_config_issues()

    return {
        "env_files": [
            {"path": str(path), "exists": path.exists()}
            for path in ENV_FILES
        ],
        "canonical_env_file": str(ROOT_ENV_FILE),
        "ignored_backend_env_file": {
            "path": str(BACKEND_ENV_FILE),
            "exists": BACKEND_ENV_FILE.exists(),
        },
        "supabase_configured": not auth_issues,
        "supabase_admin_signup_enabled": (
            settings.use_supabase_admin_signup
            and not _is_missing_or_placeholder(settings.supabase_service_key)
        ),
        "supabase_issues": auth_issues,
        "llm_provider": settings.llm_provider,
        "llm_configured": not llm_issues,
        "llm_issues": llm_issues,
        "cors_origins": settings.cors_origins,
    }
