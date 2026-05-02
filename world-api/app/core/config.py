from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    arena_shared_secret: str = "dev-secret"

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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


settings = Settings()
