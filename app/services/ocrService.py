import json
import logging
import os
from typing import Dict, Any

from dotenv import load_dotenv
from google import genai
from base64 import b64encode

from google.cloud import storage

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
gemini = genai.Client(api_key=GOOGLE_API_KEY) if (genai and GOOGLE_API_KEY) else None

# GCP Storage 설정
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

# 허용 MIME
ALLOWED_MIME = {"image/jpeg", "image/png"}

class OcrError(Exception):
    # OCR 및 관련 작업에서 발생하는 커스텀 에러
    def __init__(self, message, is_client_error=True):
        super().__init__(message)
        self._is_client_error = is_client_error

    # 4xx인지 5xx인지 반환
    def is_client_error(self):
        return self._is_client_error

logger = logging.getLogger(__name__)


# 사용자별 OCR 이미지 경로 생성
def get_user_ocr_path(user_hash: str, record_date: str, filename: str) -> str:
    return f"users/{user_hash}/ocr/{record_date}/{filename}"


def _get_bucket():
    if not GCS_BUCKET_NAME:
        raise OcrError("GCS 버킷 설정이 올바르지 않습니다.", is_client_error=False)
    client = storage.Client()
    return client.bucket(GCS_BUCKET_NAME)


# 바이트 데이터를 GCS에 업로드
def upload_to_gcs(
        file_bytes: bytes,
        user_hash: str,
        record_date: str,
        filename: str,
        content_type: str
) -> str:
    try:
        bucket = _get_bucket()

        # users/{user_hash}/ocr 경로로 저장 (파일명 ocr_{rec.record_date}_{timestamp})
        destination_blob_name = get_user_ocr_path(user_hash, record_date, filename)
        blob = bucket.blob(destination_blob_name)

        blob.upload_from_string(file_bytes, content_type=content_type)
        logger.info(f"GCS 업로드 완료: gs://{GCS_BUCKET_NAME}/{destination_blob_name}")

        return destination_blob_name
    except Exception as e:
        logger.exception("GCS 업로드 실패")
        raise OcrError("GCS 업로드 중 오류가 발생했습니다.", is_client_error=False) from e


# GCS에서 파일을 바이트로 다운로드
def download_from_gcs(gcs_path: str) -> bytes:
    try:
        bucket = _get_bucket()
        blob = bucket.blob(gcs_path)

        file_bytes = blob.download_as_bytes()
        logger.info(f"GCS 다운로드 완료: gs://{GCS_BUCKET_NAME}/{gcs_path}")

        return file_bytes
    except Exception as e:
        logger.exception("GCS 다운로드 실패")
        raise OcrError("GCS 다운로드 중 오류가 발생했습니다.", is_client_error=False) from e


def delete_from_gcs(gcs_path: str) -> None:
    try:
        bucket = _get_bucket()
        blob = bucket.blob(gcs_path)

        blob.delete()
        logger.info(f"GCS 삭제 완료: gs://{GCS_BUCKET_NAME}/{gcs_path}")
    except Exception as e:
        logger.exception("GCS 삭제 실패")
        raise OcrError("GCS 삭제 중 오류가 발생했습니다.", is_client_error=False) from e


# 바이트 + MIME 타입을 받아 gemini로 OCR을 수행 -> 텍스트를 json 형태로 반환
def ocr_bytes_to_pdrecord_json(
    file_bytes: bytes,
    content_type: str,
    model: str = "gemini-2.5-flash"
) -> Dict[str, Any]:
    if not file_bytes:
        raise OcrError("빈 파일입니다.")
    if content_type not in ALLOWED_MIME:
        allowed = ", ".join(sorted(ALLOWED_MIME))
        raise OcrError(f"지원하지 않는 형식입니다. 허용: {allowed}")

    prompt = (
        "The following image is a 'Peritoneal Dialysis Record Sheet.'"
        "Read the actual values inside the table and fill out the JSON schema below exactly."
        "Do NOT output any additional explanation or text—output JSON only.\n"
        "\n"
        "Rules:\n"
        "1. Use only the text and numbers visible in the image. If a value is not visible, do not guess—set it to null.\n"
        "2. Convert dates to the YYYY-MM-DD format. (Example: '2025년 9월 19일' → '2025-09-19')\n"
        "3. Return the day of the week as one of the following: '월', '화', '수', '목', '금', '토', '일'\n"
        "4. Convert AM/PM times to 24-hour HH:MM format. (Examples: '오전 6시' → 06:00, '오후 5시' → 17:00)\n"
        "5. For all numerical values, remove units and return only integers or floats. (Examples: '2.5%' -> 2.5, '2000g' -> 2000, '56kg' -> 56, '150/90mmHg' -> {'systolic': 150, 'diastolic':90 }, '134mg/dL' -> 134\n"
        "If the value is unclear or unreadable, return null. Remove spaces and commas.\n"
        "6. Map exchange numbers from left → right in order (1, 2, 3, …). If an exchange is empty, exclude it or return null.\n"
        "7. If a “Total Drain Volume” (제수량 합계) is present, return its numeric value. If not present, return null.\n"
        "8. Turbidity (“혼탁”) must be either '없음' or '있음'. If unclear, return null.\n"
        "9. For blood_pressure, separate into 'systolic' and 'diastolic' integers (units removed).\n"
        "10. For the “복막액 혼탁” (turbidity) checkbox section: Return '없음' or '있음' depending on which circle/check mark is selected.\n"
        "- If unclear, return null.\n"
        "- If both options are marked, set conflict: true.\n"
        "the JSON schema you must output:\n"
        "{\n"
        '  "record_date": "YYYY-MM-DD" or null,\n'
        '  "record_dw": "월" | "화" | "수" | "목" | "금" | "토" | "일" | null,\n'
        '  "exchanges": [\n'
        "    {\"exchange_no\": int, \"exchange_time\": \"HH:MM\" or null, "
        "\"drain_volume\": int or null, \"fill_concentration\": float or null, "
        "\"fill_volume\": int or null, \"uf\": int or null}\n"
        "  ],\n"
        '  "weight": float or null,\n'
        '  "blood_pressure": {"systolic": int or null, "diastolic": int or null},\n'
        '  "fasting_glucose": int or null,\n'
        '  "urine_count": int or null,\n'
        '  "turbidity": "없음" | "있음" | null,\n'
        '  "turbidity-conflict": true | false,\n'
        '  "total_uf": int or null,\n'
        '  "notes": string or null\n'
        "}\n"
    )

    encoded = b64encode(file_bytes).decode("utf-8")
    try:
        resp = gemini.models.generate_content(
            model=model,
            contents=[
                {"inline_data": {"mime_type": content_type, "data": encoded}},
                prompt,
            ],
            config={
                "response_mime_type": "application/json",
                "temperature": 0,  # 임의 생성 억제
                "top_p": 0.8,
            },
        )
        raw = (resp.text or "").strip()

        # JSON 파싱
        data = json.loads(raw)

        # 키 없으면 채워넣기
        data.setdefault("exchanges", [])
        data.setdefault("blood_pressure", {"systolic": None, "diastolic": None})
        return data

    except json.JSONDecodeError as e:
        logger.exception("모델 JSON 파싱 실패")
        raise OcrError("OCR 처리 중 서버 오류가 발생했습니다.", is_client_error=False) from e
    except Exception as e:
        logger.exception("OCR 처리 실패")
        raise OcrError("OCR 처리 중 서버 오류가 발생했습니다.", is_client_error=False) from e