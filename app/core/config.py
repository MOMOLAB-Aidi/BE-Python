from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: str
    GOOGLE_APPLICATION_CREDENTIALS: str
    GOOGLE_API_KEY: str

    GOOGLE_GENAI_USE_VERTEXAI: bool = False

    class Config:
        env_file = ".env"

settings = Settings()