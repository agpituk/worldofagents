from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Secrets we refuse to let into a running process. Every value here was
# either the historic baked-in default or the placeholder shipped in
# .env.example. Anything matching means the deployment forgot to set
# ARENA_SHARED_SECRET, and we'd rather crash on boot than sign tokens
# with a publicly-known key.
_FORBIDDEN_SECRETS = frozenset({
    "",
    "dev-secret",
    "change-me-in-prod-this-is-the-trust-anchor",
})
_MIN_SECRET_LEN = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No default — pydantic-settings will fail to construct if
    # ARENA_SHARED_SECRET is not in the environment / .env file.
    arena_shared_secret: str
    gateway_default_provider: str = "stub"   # stub | cq | any-llm | llamafile

    cq_base_url: str = ""
    cq_api_key: str = ""
    any_llm_base_url: str = ""
    llamafile_base_url: str = ""

    # Signed-token lifetime — short-lived; tokens are meant to be consumed in the same tick.
    token_ttl_seconds: int = 60

    # When true, /think rejects requests that don't carry a world-api-signed
    # permission_token. Off lets old/local callers exercise the gateway
    # without world-api in the loop (development convenience).
    require_permission_token: bool = True

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
