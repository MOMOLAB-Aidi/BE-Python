import os
from typing import Optional

from dotenv import load_dotenv
from google import genai
from base64 import b64encode


load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
gemini = genai.Client(api_key=GOOGLE_API_KEY) if (genai and GOOGLE_API_KEY) else None

# 허용 MIME
ALLOWED_MIME = {"image/jpeg", "image/png"}

class OcrError(Exception):
    # OCR 처리 중 발생한 도메인 예외
    pass

# 바이트 + MIME 타입을 받아 gemini로 OCR을 수행하고 텍스트를 반환
def ocr_bytes_to_text(
    file_bytes: bytes,
    content_type: str,
    prompt: Optional[str] = None,
    model: str = "gemini-2.5-flash",
) -> str:

    if not file_bytes:
        raise OcrError("빈 파일입니다.")
    if content_type not in ALLOWED_MIME:
        allowed = ", ".join(sorted(ALLOWED_MIME))
        raise OcrError(f"지원하지 않는 형식입니다. 허용: {allowed}")

    prompt = prompt or "이 이미지에서 모든 텍스트를 최대한 정확하게 추출하여 plain text로 제공해줘. 줄바꿈은 유지해줘."

    try:
        encoded = b64encode(file_bytes).decode("utf-8")

        response = gemini.models.generate_content(
            model=model,
            contents=[
                {"inline_data": {"mime_type": content_type, "data": encoded}},
                prompt,
            ],
        )

        text = (response.text or "").strip()
        return text
    except Exception as e:

        raise OcrError(f"OCR 처리 실패: {type(e).__name__}: {e}") from e


