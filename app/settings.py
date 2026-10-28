"""All configuration comes from environment variables. No secrets in code."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./local.db"
    # Shared secret Vapi sends on every webhook, either as "Authorization: Bearer <secret>"
    # or the legacy "X-Vapi-Secret: <secret>" header. Empty disables the check (local dev only).
    vapi_webhook_secret: str = ""
    vapi_api_key: str = ""
    public_base_url: str = "http://localhost:8000"
    # Optional API key for the REST API (header X-API-Key). Empty keeps the API open for reviewers.
    api_key: str = ""
    log_level: str = "INFO"

    @property
    def sqlalchemy_url(self) -> str:
        # Railway style URLs start with postgres:// or postgresql://.
        # SQLAlchemy needs the driver name to use psycopg 3.
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


settings = Settings()
