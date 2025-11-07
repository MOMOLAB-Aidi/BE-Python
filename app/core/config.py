import json
from typing import Optional, List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

class Settings(BaseSettings):
    # 원문 문자열(.env에서 CSV 또는 JSON 배열 문자열로)
    ALLOWED_ORIGINS_RAW: str = ""

    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        s = (self.ALLOWED_ORIGINS_RAW or "").strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                return json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in ALLOWED_ORIGINS_RAW: {e}")
        return [x.strip() for x in s.split(",") if x.strip()]

    DATABASE_URL: Optional[str] = None
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = None
    DB_NAME: Optional[str] = None
    INSTANCE_CONNECTION_NAME: Optional[str] = None

    GOOGLE_GENAI_USE_VERTEXAI: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False, # 대소문자 구분 x
        extra="ignore",
    )

settings = Settings()