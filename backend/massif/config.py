from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://massif:massif@localhost:5433/massif"
    anthropic_api_key: str = ""

    # Sent with every outbound request. Put a real contact URL here before
    # pointing this at anyone's server.
    user_agent: str = "massif/0.1 (+https://example.org/about; contact@example.org)"
    # Politeness floor: seconds between requests to the same host.
    scrape_min_interval: float = 2.0
    scrape_timeout: float = 30.0

    # A status nobody has reconfirmed within this window is shown as stale
    # rather than current.
    default_stale_days: int = 14


settings = Settings()
