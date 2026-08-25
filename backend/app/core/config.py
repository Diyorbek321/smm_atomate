"""Application settings loaded from the environment (12-factor)."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Every knob of the system lives here. Nothing is hardcoded elsewhere."""

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    app_name: str = "AutoSMM AI"
    env: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = True
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    #: Point at a self-hosted Bot API server to lift the 20 MB download cap.
    #: Empty means api.telegram.org, where bots may only fetch 20 MB files.
    telegram_api_base: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- Security --------------------------------------------------------
    api_key: str = "change-me-super-secret-api-key"
    secret_key: str = "change-me-32-chars-minimum-secret"
    encryption_key: str = ""

    # --- Database --------------------------------------------------------
    postgres_user: str = "autosmm"
    postgres_password: str = "autosmm"
    postgres_db: str = "autosmm"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --- Redis / Celery --------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- LLM provider ----------------------------------------------------
    #: Which backend writes the content. `openai` and `groq` both speak the
    #: OpenAI chat-completions protocol, so any compatible endpoint works.
    llm_provider: Literal["gemini", "openai", "groq"] = "gemini"
    #: Providers to fall back to when the primary is rate-limited or down, in
    #: order, comma separated. A paid service cannot stop for a daily quota.
    llm_fallbacks: str = "groq,gemini"
    llm_max_output_tokens: int = 4096
    llm_temperature: float = 0.9

    # --- Gemini ----------------------------------------------------------
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model_fast: str = "gemini-1.5-flash"
    gemini_model_pro: str = "gemini-1.5-pro"
    gemini_max_output_tokens: int = 4096
    gemini_temperature: float = 0.9
    #: Gemini 2.5+/3.x spend output tokens on hidden reasoning, which both
    #: truncates answers and inflates cost. 0 disables it; -1 lets the model
    #: decide; a positive number caps it.
    gemini_thinking_budget: int | None = 0

    # --- OpenAI-compatible providers -------------------------------------
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_pro: str = "gpt-4o"

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model_fast: str = "openai/gpt-oss-20b"
    groq_model_pro: str = "openai/gpt-oss-120b"

    # --- Images ----------------------------------------------------------
    image_provider: Literal["fal", "replicate", "none"] = "fal"
    fal_api_key: str = ""
    fal_model: str = "fal-ai/flux/schnell"
    #: Image-to-video model for AI-animated clips (Seedance/Kling on fal.ai).
    fal_video_model: str = "fal-ai/bytedance/seedance/v1/lite/image-to-video"
    replicate_api_token: str = ""
    replicate_model: str = "black-forest-labs/flux-schnell"

    # --- Transcription ---------------------------------------------------
    transcription_provider: Literal["openai", "groq", "gemini"] = "openai"
    openai_api_key: str = ""
    whisper_model: str = "whisper-1"
    groq_whisper_model: str = "whisper-large-v3"

    # --- Telegram --------------------------------------------------------
    telegram_bot_token: str = ""
    telegram_use_webhook: bool = False
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    telegram_admin_ids: str = ""

    # --- Meta / Instagram ------------------------------------------------
    meta_graph_version: str = "v21.0"
    meta_graph_base: str = "https://graph.facebook.com"
    meta_app_id: str = ""
    meta_app_secret: str = ""

    # --- Media -----------------------------------------------------------
    media_root: Path = BASE_DIR / "media"
    media_url_prefix: str = "/media"
    media_retention_days: int = 45
    #: Kinetic clips are authored on a 720x1280 grid; 1.5 delivers 1080x1920,
    #: the resolution Instagram and TikTok actually want. Lower it to render faster.
    kinetic_scale: float = 1.5

    # --- Video delivery --------------------------------------------------
    #: What leaves this system is a master that Telegram and Instagram will
    #: re-encode, so it is deliberately better than the file the viewer gets.
    #: Raise the CRF or pick a faster preset to trade quality for render time.
    video_crf: int = 18
    video_preset: str = "slow"
    audio_bitrate: str = "192k"

    # --- Image quality per tier ------------------------------------------
    #: Flux Schnell is a 4-step distilled model: fast, cheap and visibly
    #: rougher. Paying clients get a real sampler, and the tier decides which
    #: (see app/core/plans.py). Schnell has no CFG, so a negative prompt is
    #: only sent to the models that can act on one.
    fal_model_start: str = "fal-ai/flux/schnell"
    fal_model_standard: str = "fal-ai/flux/dev"
    fal_model_pro: str = "fal-ai/flux-pro/v1.1"

    # --- Visual quality gate ---------------------------------------------
    #: Show every finished render to a multimodal model before it reaches the
    #: owner's review queue. Costs a fraction of a cent per image and catches
    #: the renders that are visibly broken — clipped text above all.
    visual_qc: bool = True
    #: Below this the render is attempted once more; the better of the two wins.
    visual_qc_min_score: int = 7

    # --- Second-layer agents ---------------------------------------------
    #: These sit above the agents that already existed and hand them a brief;
    #: each one is a separate LLM call, so they are switchable per deployment.
    #
    #: Once per plan (weekly) — decides the commercial angle the strategist
    #: then turns into dates. Cheap at this cadence, so it defaults on.
    use_marketolog_agent: bool = True
    #: Per post: rewrites the first line after the copy is approved.
    use_hook_agent: bool = True
    #: Per post: decides the card composition before the visual agent renders.
    use_designer_agent: bool = True
    #: The two per-post agents together add roughly 15-20% to the cost of a
    #: post (four LLM calls become six). Turn them off first when a provider
    #: budget bites.
    #
    #: Once per plan (weekly) — reads what the last month produced and earned,
    #: and hands its recommendations to the marketolog. Off when the marketolog
    #: is off: nothing downstream would read the report.
    use_analyst_agent: bool = True
    #: How many days of production the analyst reads. A month is the shortest
    #: window that contains enough posts to compare pillars at all.
    analyst_window_days: int = 30
    #: On ingest — mines checkable facts out of what the owner sent and appends
    #: them to the knowledge base's notes. One extra call per *document*; short
    #: chat messages skip it (see `research_min_chars`).
    use_researcher_agent: bool = True
    #: Free-form text shorter than this is a chat reply, not a source worth
    #: mining; onboarding's structured extraction already handles it.
    research_min_chars: int = 400
    #: Per edited video — reads the transcript and decides which parts survive,
    #: instead of keeping whatever is not silence. Costs one LLM call and one
    #: extra Whisper pass over the source; falls back to silence-trim on any
    #: failure.
    use_video_editor_agent: bool = True

    # --- Behaviour -------------------------------------------------------
    default_timezone: str = "Asia/Tashkent"
    default_language: str = "uz"
    http_timeout: int = 60
    ai_max_retries: int = 3
    max_publish_retries: int = 3
    publish_batch_size: int = 25
    #: Posts generated in parallel. Lower it when the LLM has a tight
    #: tokens-per-minute budget (Groq's free tier allows 8k/min).
    generation_concurrency: int = 3
    #: Seconds a process may block waiting out a provider rate limit.
    #: Interactive processes stay low; workers are given a bigger budget
    #: because nobody is watching them.
    llm_max_retry_wait: float = 30.0
    auto_approve: bool = False

    # ------------------------------------------------------------------ #
    # Validators / computed values
    # ------------------------------------------------------------------ #
    @field_validator("media_root", mode="before")
    @classmethod
    def _expand_media_root(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_database_url(self) -> str:
        """SQLAlchemy async DSN (asyncpg driver)."""
        if self.database_url:
            url = self.database_url
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Blocking DSN — used by Alembic migrations."""
        return self.async_database_url.replace("+asyncpg", "+psycopg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def admin_ids(self) -> set[int]:
        ids: set[int] = set()
        for chunk in self.telegram_admin_ids.split(","):
            chunk = chunk.strip()
            if chunk.lstrip("-").isdigit():
                ids.add(int(chunk))
        return ids

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fernet_key(self) -> bytes:
        """Return a valid Fernet key, derived from SECRET_KEY when not set."""
        if self.encryption_key:
            return self.encryption_key.encode()
        digest = hashlib.sha256(self.secret_key.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def graph_api_url(self) -> str:
        return f"{self.meta_graph_base.rstrip('/')}/{self.meta_graph_version}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_key(self) -> str:
        """API key for the configured LLM provider."""
        if self.llm_provider == "gemini":
            return self.gemini_api_key
        if self.llm_provider == "groq":
            return self.groq_api_key
        return self.openai_api_key

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_base_url(self) -> str:
        return self.groq_base_url if self.llm_provider == "groq" else self.openai_base_url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_model_fast(self) -> str:
        if self.llm_provider == "gemini":
            return self.gemini_model_fast
        return self.groq_model_fast if self.llm_provider == "groq" else self.openai_model_fast

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_model_pro(self) -> str:
        if self.llm_provider == "gemini":
            return self.gemini_model_pro
        return self.groq_model_pro if self.llm_provider == "groq" else self.openai_model_pro

    def media_url(self, filename: str) -> str:
        """Absolute, publicly reachable URL for a stored media file."""
        return f"{self.public_base_url.rstrip('/')}{self.media_url_prefix}/{filename}"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
