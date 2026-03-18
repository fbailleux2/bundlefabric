"""BundleFabric MCP — Settings (pydantic-settings, env var driven)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # BundleFabric API
    api_url: str = "https://api.bundlefabric.org"
    api_key: str = ""  # bf_<user>_<hex>  — required at runtime

    # Tailscale URL for SSE streaming (requires X-Tailscale-Access header)
    tailscale_url: str = "http://100.84.103.104:19100"

    # Execution
    execute_timeout: float = 120.0   # seconds — Ollama CPU ~60-120s

    # Dynamic bundle tools — max bundles to register as MCP tools at startup
    max_bundles: int = 20

    # Logging
    log_level: str = "INFO"


settings = Settings()
