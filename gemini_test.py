import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

# 환경변수 확인
cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_env or not Path(cred_env).exists():
    raise FileNotFoundError(
        f"환경변수 GOOGLE_APPLICATION_CREDENTIALS가 비어있거나 파일이 없습니다: {cred_env}"
    )

# 환경변수 기반으로 자동 인증
client = genai.Client()

response = client.models.generate_content(
    model = "gemini-2.5-flash",
    contents = "How does AI work?"
)
print(response.text)