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


settings = Settings()
