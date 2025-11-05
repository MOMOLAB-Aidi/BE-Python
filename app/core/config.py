from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: Optional[str] = None
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = None
    DB_NAME: Optional[str] = None

    GOOGLE_GENAI_USE_VERTEXAI: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False, # 대소문자 구분 x
        extra="ignore",
    )

settings = Settings()