from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Mirror llm-gateway/app/config.py: anything in this set means the
# deployment hasn't actually set ARENA_SHARED_SECRET, so we refuse to
# boot rather than sign tokens with a publicly-known value.
_FORBIDDEN_SECRETS = frozenset({
    "",
    "dev-secret",
    "change-me-in-prod-this-is-the-trust-anchor",
})
_MIN_SECRET_LEN = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No default — boot fails if ARENA_SHARED_SECRET is not set.
    arena_shared_secret: str

    postgres_user: str = "arena"
    postgres_password: str = "arena"
    postgres_db: str = "arena"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_host: str = "localhost"
    redis_port: int = 6379

    world_tick_seconds: float = 6.0
    gateway_base_url: str = "http://llm-gateway:8001"

    # Phase 6 — total skill XP a hero can accumulate across all skills
    # combined. UO's 700-point cap was the single biggest driver of build
    # diversity in that game; this is the same idea translated to XP
    # (1000 XP per skill = level 100). Default `0` = uncapped (the
    # legacy behaviour); a hero opts in via `manifest.build.skill_cap`.
    # Heroes still gain XP up to the cap; over-cap grants are silently
    # dropped at the `_grant_xp` boundary, so the verb still resolves
    # — just no skill bump. Reflex DSL gets `skill_points_remaining`.
    skill_cap_total_default: int = 0

    # Comma-separated list of allowed CORS origins for the spectator UI.
    # Defaults to the dev frontend; override in production. Set to `*` to
    # restore the historic wildcard (only safe because we don't allow
    # credentials), but pinning is the recommended posture.
    cors_allow_origins: str = (
        "http://localhost:47900,http://127.0.0.1:47900"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @field_validator("arena_shared_secret")
    @classmethod
    def _reject_weak_secret(cls, v: str) -> str:
        if v in _FORBIDDEN_SECRETS:
            raise ValueError(
                "ARENA_SHARED_SECRET is unset or matches a known placeholder; "
                "set it to a fresh random value (>=16 chars)"
            )
        if len(v) < _MIN_SECRET_LEN:
            raise ValueError(
                f"ARENA_SHARED_SECRET must be at least {_MIN_SECRET_LEN} chars"
            )
        return v


settings = Settings()
