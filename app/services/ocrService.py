import json
import os
from typing import Optional, Dict, Any

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

# 바이트 + MIME 타입을 받아 gemini로 OCR을 수행하고 텍스트를 json 형태로 반환
def ocr_bytes_to_pdrecord_json(
    file_bytes: bytes,
    content_type: str,
    model: str = "gemini-2.5-flash",
) -> Dict[str, Any]:
    if not file_bytes:
        raise OcrError("빈 파일입니다.")
    if content_type not in ALLOWED_MIME:
        allowed = ", ".join(sorted(ALLOWED_MIME))
        raise OcrError(f"지원하지 않는 형식입니다. 허용: {allowed}")

    prompt = (
        "다음 이미지는 '복막투석기록일지'야. 표 안의 **실제 값**을 읽어 "
        "아래 JSON 스키마에 맞춰 **정확히** 채워 반환해줘. "
        "추가 설명/텍스트는 절대 출력하지 말고, **JSON만** 출력해줘.\n"
        "\n"
        "규칙:\n"
        "1) 이미지에 보이는 텍스트와 숫자만 사용해줘. 보이지 않는 값은 추측하지 말고 null로 둬.\n"
        "2) 날짜는 YYYY-MM-DD로 변환(예: 2025년 9월 19일 → 2025-09-19).\n"
        "3) 요일은 '월','화','수','목','금','토','일' 중 하나로 반환.\n"
        "4) 시간은 오전/오후를 24시간제로 변환하여 HH:MM 형식으로 반환(예: 오전 6시 → 06:00, 오후 5시 → 17:00).\n"
        "5) 수치는 단위를 제거하고 정수/실수로만 기록(예: 2.5%, 2000 g, 56 kg, 150/90 mmHg, 134 mg/dL 등). "
        "읽기 어려우면 null. 공백/쉼표 제거.\n"
        "6) 표의 교환 회차는 좌→우 순서대로 1,2,3,... 로 매핑해줘. 비어 있으면 그 회차는 제외하거나 null 처리.\n"
        "7) '제수량 합계'가 표에 있으면 숫자로 반환. 없으면 null.\n"
        "8) 혼탁(turbidity)은 '없음' 또는 '있음' 중 택1, 불명확하면 null.\n"
        "9) blood_pressure는 'systolic'(수축)와 'diastolic'(이완)로 분리, 단위를 제외한 정수.\n"
        "\n"
        "반환 JSON 스키마:\n"
        "{\n"
        '  "record_date": "YYYY-MM-DD" | null,\n'
        '  "record_dw": "월" | "화" | "수" | "목" | "금" | "토" | "일" | null,\n'
        '  "exchanges": [\n'
        "    {\"exchange_no\": int, \"exchange_time\": \"HH:MM\" | null, "
        "\"drain_volume\": int | null, \"fill_concentration\": float | null, "
        "\"fill_volume\": int | null, \"uf\": int | null}\n"
        "  ],\n"
        '  "weight": float | null,\n'
        '  "blood_pressure": {"systolic": int | null, "diastolic": int | null},\n'
        '  "fasting_glucose": int | null,\n'
        '  "urine_count": int | null,\n'
        '  "turbidity": "없음" | "있음" | null,\n'
        '  "total_uf": int | null,\n'
        '  "notes": string | null\n'
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

    except json.JSONDecodeError:
        # 모델이 JSON 이외를 출력했다면 예외 처리
        raise OcrError("모델이 JSON이 아닌 응답을 반환했습니다. 프롬프트/이미지를 확인하세요.")
    except Exception as e:
        raise OcrError(f"OCR 처리 실패: {type(e).__name__}: {e}") from e


