from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-this-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours (full work shift)

    DATABASE_URL: str = "postgresql://kedco:password@localhost:5432/kedco_db"

    ERPNEXT_URL: str = ""
    ERPNEXT_API_KEY: str = ""
    ERPNEXT_API_SECRET: str = ""

    ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
