"""Application configuration — env vars only, no secrets committed."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "EVE Healthcare"
    ENV: str = "dev"
    API_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+psycopg2://eve:evepass@localhost:5432/eve"
    TEST_DATABASE_URL: str = ""

    JWT_SECRET: str = "change-me-to-a-long-random-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    WEBHOOK_SECRET: str = "change-me-webhook-secret"

    ADMIN_EMAIL: str = "admin@eve.local"
    ADMIN_PASSWORD: str = "Adminpass123"
    ADMIN_NAME: str = "Admin"

    LOG_LEVEL: str = "INFO"


settings = Settings()
