import json
import os
from datetime import date, datetime, time
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
from fastapi import HTTPException
from google import genai
from base64 import b64encode

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_models.record import Record
from app.db_models.record_exchange import RecordExchange

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
gemini = genai.Client(api_key=GOOGLE_API_KEY) if (genai and GOOGLE_API_KEY) else None

# 허용 MIME
ALLOWED_MIME = {"image/jpeg", "image/png"}

class OcrError(Exception):
    # OCR 처리 중 발생한 도메인 예외
    pass

# 바이트 + MIME 타입을 받아 gemini로 OCR을 수행 -> 텍스트를 json 형태로 반환
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
        "10) - '복막액 혼탁' 항목은 '없음'과 '있음' 중 동그라미/체크 표시된 쪽을 읽어 반환하라.\n"
        "- 명확히 판별되지 않으면 null로 둬라.\n"
        "- 두 항목 모두 표시되었으면 conflict: true 로 표시하라.\n"
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
        '  "turbidity-conflict": true | false,\n'
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

    # 모델이 JSON 이외의 응답을 출력하는 경우
    except json.JSONDecodeError:
        raise OcrError("모델이 JSON이 아닌 응답을 반환했습니다. 프롬프트/이미지를 확인하세요.")
    except Exception as e:
        raise OcrError(f"OCR 처리 실패: {type(e).__name__}: {e}") from e


WEEK_KR = ["월","화","수","목","금","토","일"]

def _parse_date(s: Optional[str]) -> date:
    if not s:
        raise ValueError("record_date가 필요합니다(YYYY-MM-DD).")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise ValueError(f"record_date 형식 오류: {s}")

def _parse_time_hhmm(s: Optional[str]) -> time:
    if not s:
        raise ValueError("exchange_time이 필요합니다(HH:MM).")
    try:
        return datetime.strptime(s, "%H:%M").time()
    except Exception:
        raise ValueError(f"exchange_time 형식 오류: {s}")


def _to_int_required(x, field: str) -> int:
    if x is None or x == "":
        raise ValueError(f"{field} 값이 필요합니다.")
    try:
        return int(x)
    except Exception:
        raise ValueError(f"{field} 정수 변환 실패: {x}")


def _to_float_required(x, field: str) -> float:
    if x is None or x == "":
        raise ValueError(f"{field} 값이 필요합니다.")
    try:
        return float(x)
    except Exception:
        raise ValueError(f"{field} 실수 변환 실패: {x}")


# 요일은 '월'~'일' 중 하나여야 하며 JSON에 없거나 잘못되면 날짜로부터 계산
def _norm_dayweek(dw: Optional[str], d: date) -> str:
    if dw in WEEK_KR:
        return dw
    return WEEK_KR[d.weekday()]


# OCR 구조화 JSON을 받아 db에 저장 (중복 날짜는 409 반환)
def save_pdrecord_json(data: Dict[str, Any], db: Session) -> Record:
    record_date = _parse_date(data.get("record_date"))
    record_dw = _norm_dayweek(data.get("record_dw"), record_date)

    weight = _to_float_required(data.get("weight"), "weight")
    bp = data.get("blood_pressure") or {}
    systolic = _to_int_required(bp.get("systolic"), "blood_pressure.systolic")
    diastolic = _to_int_required(bp.get("diastolic"), "blood_pressure.diastolic")
    fasting_glucose = _to_int_required(data.get("fasting_glucose"), "fasting_glucose")
    urine_count = _to_int_required(data.get("urine_count"), "urine_count")

    turbidity = data.get("turbidity")
    if turbidity not in ("없음", "있음"):
        raise ValueError("turbidity는 '없음' 또는 '있음'이어야 합니다.")

    notes = data.get("notes")
    total_uf = _to_int_required(data.get("total_uf"), "total_uf")

    # 동일 날짜 존재 여부 체크
    existing = (
        db.query(Record)
        .filter(Record.record_date == record_date)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{record_date.isoformat()} 해당 기록이 이미 존재합니다."
        )

    record = Record(
        record_date=record_date,
        record_dw=record_dw,
        weight=weight,
        systolic=systolic,
        diastolic=diastolic,
        fasting_glucose=fasting_glucose,
        urine_count=urine_count,
        turbidity=turbidity,
        notes=notes,
        total_uf=total_uf,
    )
    db.add(record)
    db.flush()  # record.id 확보

    # 교환회차
    exchanges: List[Dict[str, Any]] = data.get("exchanges") or []
    if not exchanges:
        raise ValueError("exchanges가 비어 있습니다.")

    rows: List[RecordExchange] = []
    for ex in exchanges:
        ex_no = _to_int_required(ex.get("exchange_no"), "exchanges[].exchange_no")
        ex_time = _parse_time_hhmm(ex.get("exchange_time"))
        drain_v = _to_int_required(ex.get("drain_volume"), "exchanges[].drain_volume")
        fill_v = _to_int_required(ex.get("fill_volume"), "exchanges[].fill_volume")
        fill_c = _to_float_required(ex.get("fill_concentration"), "exchanges[].fill_concentration")
        uf = _to_int_required(ex.get("uf"), "exchanges[].uf")

        rows.append(
            RecordExchange(
                record_id=record.id,
                exchange_no=ex_no,
                exchange_time=ex_time,
                drain_volume=drain_v,
                fill_volume=fill_v,
                fill_concentration=fill_c,
                uf=uf,
            )
        )

    try:
        db.add_all(rows)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
                status_code=409,
                detail = f"{record_date.isoformat()} 해당 기록이 이미 존재합니다.",
        ) from e
    db.refresh(record)
    return record


# Record 객체를 응답 JSON으로 직렬화
def _record_to_dict(rec) -> dict:
    def _t(t):
        return t.strftime("%H:%M") if t else None

    return {
        "id": rec.id,
        "record_date": rec.record_date.isoformat(),
        "record_dw": rec.record_dw,
        "weight": rec.weight,
        "systolic": rec.systolic,
        "diastolic": rec.diastolic,
        "fasting_glucose": rec.fasting_glucose,
        "urine_count": rec.urine_count,
        "turbidity": rec.turbidity,
        "notes": rec.notes,
        "total_uf": rec.total_uf,
        "exchanges": [
            {
                "id": ex.id,
                "exchange_no": ex.exchange_no,
                "exchange_time": _t(ex.exchange_time),
                "drain_volume": ex.drain_volume,
                "fill_volume": ex.fill_volume,
                "fill_concentration": ex.fill_concentration,
                "uf": ex.uf,
            }
            for ex in (rec.exchanges or [])
        ],
    }