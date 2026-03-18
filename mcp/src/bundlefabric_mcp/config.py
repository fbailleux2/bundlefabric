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

    # Transport
    transport: str = "stdio"  # "stdio" for Claude Desktop, "sse" for remote

    # Logging
    log_level: str = "INFO"


settings = Settings()
