"""Application settings loaded from environment with sensible defaults."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GROUP_INSURE_", extra="ignore")

    # Databases
    database_url: str = "postgresql+psycopg2://group_insure:group_insure@localhost:5432/group_insure"

    # Auth
    jwt_secret: str = "change-me-in-production-group-insure-secret"
    jwt_algorithm: str = "HS256"
    jwt_expiry_seconds: int = 60 * 60 * 8  # 8 hours
    bcrypt_rounds: int = 12

    # Email (SMTP). Defaults to disabled so the app never attempts a real send
    # in development or test; the send endpoint then refuses with 400.
    smtp_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    email_from: str = "no-reply@group-insure.local"


settings = Settings()
