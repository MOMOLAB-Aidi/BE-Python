import io
import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import speech

# 1) .env 로드 (동일 경로/프로젝트 루트에 .env가 있어야 함)
load_dotenv()

# 2) 환경변수 확인 (없으면 친절히 에러)
cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_env or not Path(cred_env).exists():
    raise FileNotFoundError(
        f"환경변수 GOOGLE_APPLICATION_CREDENTIALS가 비어있거나 파일이 없습니다: {cred_env}"
    )

# 3) 환경변수 기반으로 자동 인증 (credentials 인자 제거!)
client = speech.SpeechClient()

# 4) 오디오 파일 절대 경로 지정
audio_path = r"C:\Users\user1\PycharmProjects\PythonProject\BE-Python\sample.wav"
if not Path(audio_path).exists():
    raise FileNotFoundError(f"오디오 파일을 찾을 수 없습니다: {audio_path}")

# 5) 파일 로드
with io.open(audio_path, "rb") as f:
    content = f.read()

# dict로 요청 구성
config = {
    "encoding": speech.RecognitionConfig.AudioEncoding.LINEAR16,
    "language_code": "ko-KR",
    "enable_automatic_punctuation": True,
}
audio = {"content": content}

response = client.recognize(request={"config": config, "audio": audio})
for r in response.results:
    print(r.alternatives[0].transcript)
