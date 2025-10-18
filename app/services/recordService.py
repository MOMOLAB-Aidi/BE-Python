import re, os, json
from datetime import time as dtime, date
from typing import Dict, Any

from dotenv import load_dotenv
from fastapi import HTTPException

from app.db_models.record import Record
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini = genai.Client(api_key=GEMINI_API_KEY) if (genai and GEMINI_API_KEY) else None


# 시간 형식 검증
def parse_time(s: str) -> dtime:
    s = (s or "").strip().replace("시", ":").replace(".", ":")
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", s)
    if not m: raise ValueError("시간은 HH:MM 형식")
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59): raise ValueError("시간 범위 오류")
    return dtime(hour=hh, minute=mm)


# 날짜 형식 변환
def _format_date_kr(d: date | None) -> str:
    if not d:
        return ""
    return f"{d.year}년 {d.month}월 {d.day}일"


# dict 형식으로 변환
def rec_to_dict(r: Record) -> Dict[str, Any]:
    return {
        "id": r.id,
        "record_date": r.record_date.isoformat() if r.record_date else None,
        "record_time": r.record_time.strftime("%H:%M") if r.record_time else None,
        "exchange_count": r.exchange_count,
        "systolic": r.systolic,
        "diastolic": r.diastolic,
        "weight_kg": r.weight_kg,
        "outflow_ml": r.outflow_ml,
        "clarity": r.clarity,
        "abdominal_pain": r.abdominal_pain,
        "exit_site": r.exit_site,
    }


# 수정사항 적용
def apply_patch(rec: Record, p: Dict[str, Any]):
    # 값 검증
    def vrng(cond, msg):
        if not cond: raise HTTPException(status_code=400, detail=msg)

    if "time" in p and p["time"] is not None:
        rec.time = parse_time(p["time"])

    if "exchange_count" in p and p["exchange_count"] is not None:
        c = int(p["exchange_count"])
        vrng(1 <= c <= 10, "교환회차 1~10")
        rec.exchange_count = c

    if "systolic" in p and p["systolic"] is not None:
        s = int(p["systolic"])
        vrng(70 <= s <= 240, "수축기 70~240")
        rec.systolic = s

    if "diastolic" in p and p["diastolic"] is not None:
        d = int(p["diastolic"])
        vrng(40 <= d <= 160, "이완기 40~160")
        rec.diastolic = d

    if "weight_kg" in p and p["weight_kg"] is not None:
        w = float(p["weight_kg"])
        vrng(20.0 <= w <= 300.0, "체중 20~300kg")
        rec.weight_kg = round(w, 1)

    if "outflow_ml" in p and p["outflow_ml"] is not None:
        o = int(p["outflow_ml"])
        vrng(0 <= o <= 5000, "유출량 0~5000mL")
        rec.outflow_ml = o

    ENUMS = {
        "clarity": {"맑음", "탁함"},  # 혼탁도
        "abdominal_pain": {"없음", "이상"},  # 복통
        "exit_site": {"정상", "이상"},  # 주사구
    }
    if "clarity" in p and p["clarity"] is not None:
        vrng(p["clarity"] in ENUMS["clarity"], "clarity 값 오류")
        rec.clarity = p["clarity"]
    if "abdominal_pain" in p and p["abdominal_pain"] is not None:
        vrng(p["abdominal_pain"] in ENUMS["abdominal_pain"], "abdominal_pain 값 오류")
        rec.abdominal_pain = p["abdominal_pain"]
    if "exit_site" in p and p["exit_site"] is not None:
        vrng(p["exit_site"] in ENUMS["exit_site"], "exit_site 값 오류")
        rec.exit_site = p["exit_site"]


def agent_text_to_patch(text: str) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}

    # 빠른 정규식 파서
    m = re.search(r'(\d{2,3})\s*[/]\s*(\d{2,3})', text)
    if m:
        patch["systolic"] = int(m.group(1))
        patch["diastolic"] = int(m.group(2))
    m = re.search(r'\b([01]?\d|2[0-3])[:\.]\s?([0-5]\d)\b', text)
    if m:
        h, mi = m.groups();
        patch["time"] = f"{int(h):02d}:{int(mi):02d}"
    m = re.search(r'(\d{2,3}(?:[.,]\d)?)\s*kg', text, re.IGNORECASE)
    if m:
        patch["weight_kg"] = float(m.group(1).replace(",", "."))
    m = re.search(r'(\d{3,4})\s*mL', text, re.IGNORECASE)
    if m:
        patch["outflow_ml"] = int(m.group(1))
    m = re.search(r'(\d{1,2})\s*회차', text)
    if m:
        patch["exchange_count"] = int(m.group(1))
    t = text
    if "혼탁" in t and ("맑" in t or "투명" in t): patch["clarity"] = "맑음"
    if "혼탁" in t and ("탁" in t or "흐림" in t): patch["clarity"] = "탁함"
    if "복통" in t and ("없" in t or "아니" in t or "무"): patch["abdominal_pain"] = "없음"
    if "복통" in t and ("있" in t or "이상" in t or "통증"): patch["abdominal_pain"] = "이상"
    if "주사구" in t and ("정상" in t or "괜찮"): patch["exit_site"] = "정상"
    if "주사구" in t and ("이상" in t or "발적" in t or "분비"): patch["exit_site"] = "이상"

    if patch or not gemini:
        return patch

    # Gemini 보조
    system = (
        "너는 복막투석 기록 업데이트 보조 에이전트야. "
        "사용자의 한국어 지시에서 해당되는 키만 JSON으로 반환해줘. "
        "키: systolic(int), diastolic(int), weight_kg(float), outflow_ml(int), "
        "exchange_count(int), time('HH:MM'), clarity('맑음'|'탁함'), "
        "abdominal_pain('없음'|'이상'), exit_site('정상'|'이상'). "
        "없는 키는 포함하지 말고 숫자는 단위 제거해줘."
    )
    prompt = f"{system}\n\n사용자 발화: {text}\n\n응답 예시: {{\"systolic\":120,\"diastolic\":80}}"
    try:
        resp = gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [prompt]}],
            config={"temperature": 0.1}
        )
        j = json.loads(resp.text.strip())
        if isinstance(j, dict):
            patch.update(j)
    except Exception:
        pass
    return patch
