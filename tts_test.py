import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import texttospeech

load_dotenv()

# 환경변수 확인
cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_env or not Path(cred_env).exists():
    raise FileNotFoundError(
        f"환경변수 GOOGLE_APPLICATION_CREDENTIALS가 비어있거나 파일이 없습니다: {cred_env}"
    )

# 환경변수 기반으로 자동 인증
client = texttospeech.TextToSpeechClient()

# dict로 요청 구성
request = {
    "input": {  # 음성으로 변환할 텍스트 설정
        # "text": "You're welcome. Have a safe and pleasant flight!"
        "text": "안녕하세요. google speech tts 실습입니다."
    },
    "voice": {  # 사용할 음성의 언어 코드와 성별 설정
        "language_code": "ko-KR",   # 한국어면 "ko-KR"
        "ssml_gender": "NEUTRAL",   # "MALE", "FEMALE", "NEUTRAL"
    },
    "audio_config": {  # 반환받을 오디오 형식 설정
        "audio_encoding": "MP3",    # "MP3", "LINEAR16", "OGG_OPUS" 등
    },
}

# 딕셔너리 기반 요청으로 호출
response = client.synthesize_speech(request=request)

# 파일로 저장하여 실제 오디오로 재생 가능
out_path = "output.mp3"
with open(out_path, "wb") as out:
    out.write(response.audio_content)
    print('Audio content written to file "{out_path}"')