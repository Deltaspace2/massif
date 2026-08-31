from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://massif:massif@localhost:5433/massif"
    anthropic_api_key: str = ""

    # Is there a transaction-mode connection pooler in front of Postgres?
    # Supabase's :6543 and PgBouncer in transaction mode both are. Left as
    # None it is inferred from the URL, which is right every time so far;
    # set DATABASE_POOLED explicitly for a pooler that does not advertise
    # itself in the port or the query string.
    database_pooled: bool | None = None

    # Sent with every outbound request. Put a real contact URL here before
    # pointing this at anyone's server.
    user_agent: str = "massif/0.1 (+https://example.org/about; contact@example.org)"
    # Politeness floor: seconds between requests to the same host.
    scrape_min_interval: float = 2.0
    scrape_timeout: float = 30.0

    # A status nobody has reconfirmed within this window is shown as stale
    # rather than current.
    default_stale_days: int = 14

    @property
    def pooled(self) -> bool:
        """Whether connections are handed out per-transaction rather than
        per-session.

        The distinction is not cosmetic: it decides whether prepared
        statements are safe, and getting it wrong produces errors that only
        appear under concurrency.
        """
        if self.database_pooled is not None:
            return self.database_pooled
        return ":6543" in self.database_url or "pgbouncer=true" in self.database_url


settings = Settings()
