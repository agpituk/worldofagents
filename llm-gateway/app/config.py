from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    arena_shared_secret: str = "dev-secret"
    gateway_default_provider: str = "stub"   # stub | cq | any-llm | llamafile

    cq_base_url: str = ""
    cq_api_key: str = ""
    any_llm_base_url: str = ""
    llamafile_base_url: str = ""

    # Signed-token lifetime — short-lived; tokens are meant to be consumed in the same tick.
    token_ttl_seconds: int = 60


settings = Settings()
