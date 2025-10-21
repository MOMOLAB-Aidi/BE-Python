import re, os, json
from datetime import time as dtime, date
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import HTTPException

from app.db_models.record import Record
from google import genai

from app.db_models.record_exchange import RecordExchange

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini = genai.Client(api_key=GEMINI_API_KEY) if (genai and GEMINI_API_KEY) else None


# 공통 유틸
def vrng(cond: bool, msg: str):
    if not cond:
        raise HTTPException(status_code=400, detail=msg)

# 시간 형식 검증
def parse_time(s: str) -> dtime:
    s = (s or "").strip().replace("시", ":").replace(".", ":")
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", s)
    if not m:
        raise ValueError("시간은 HH:MM 형식이어야 합니다.")
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("시간 범위 오류(0~23시, 0~59분)")
    return dtime(hour=hh, minute=mm)


# 날짜 형식 변환
def _format_date_kr(d: Optional[date]) -> str:
    if not d:
        return ""
    return f"{d.year}년 {d.month}월 {d.day}일"

# dict 형식으로 변환
def ex_to_dict(e: RecordExchange) -> Dict[str, Any]:
    return {
        "id": e.id,
        "exchange_no": e.exchange_no,
        "exchange_time": e.exchange_time.strftime("%H:%M") if e.exchange_time else None,
        "drain_volume": e.drain_volume,
        "fill_volume": e.fill_volume,
        "fill_concentration": e.fill_concentration,
        "uf": ( (e.drain_volume or 0) - (e.fill_volume or 0) )
    }

# dict 형식으로 변환
def rec_to_dict(r: Record) -> Dict[str, Any]:
    return {
        "id": r.id,
        "record_date": r.record_date,
        "weight": r.weight,
        "systolic": r.systolic,
        "diastolic": r.diastolic,
        "fasting_glucose": r.fasting_glucose,
        "urine_count": r.urine_count,
        "turbidity": r.turbidity,
        "notes": r.notes,

        "total_uf": sum((e.drain_volume or 0) - (e.fill_volume or 0) for e in (r.exchanges or [])),
        "exchanges": [ex_to_dict(e) for e in (r.exchanges or [])],
    }


# 공통 수정사항 적용
def apply_record_patch(rec: Record, p: Dict[str, Any]) -> None:
    if "weight" in p and p["weight"] is not None:
        w = float(p["weight"])
        vrng(20.0 <= w <= 300.0, "체중 20~300kg")
        rec.weight = round(w, 1)

    if "systolic" in p and p["systolic"] is not None:
        s = int(p["systolic"])
        vrng(70 <= s <= 240, "수축기 70~240")
        rec.systolic = s

    if "diastolic" in p and p["diastolic"] is not None:
        d = int(p["diastolic"])
        vrng(40 <= d <= 160, "이완기 40~160")
        rec.diastolic = d

    if "fasting_glucose" in p and p["fasting_glucose"] is not None:
        g = int(p["fasting_glucose"])
        vrng(40 <= g <= 600, "공복혈당 40~600 mg/dL")
        rec.fasting_glucose = g

    if "urine_count" in p and p["urine_count"] is not None:
        u = int(p["urine_count"])
        vrng(0 <= u <= 50, "소변 횟수 0~50회")
        rec.urine_count = u

    if "turbidity" in p and p["turbidity"] is not None:
        vrng(p["turbidity"] in {"없음", "있음"}, "turbidity 값 오류(없음/있음)")
        rec.turbidity = p["turbidity"]

    if "notes" in p and p["notes"] is not None:
        rec.notes = str(p["notes"])[:2000]


# 패치 적용: 회차(개별) 수정사항 적용
def upsert_exchange(rec: Record, p: Dict[str, Any]) -> RecordExchange:
    vrng("exchange_no" in p and p["exchange_no"] is not None, "회차(개별)에는 exchange_no가 필요합니다.")
    ex_no = int(p["exchange_no"])
    vrng(1 <= ex_no <= 12, "회차는 1~12 범위")

    # 이미 로딩된 관계에서 탐색
    target = None
    if rec.exchanges:
        for e in rec.exchanges:
            if e.exchange_no == ex_no:
                target = e
                break

    # 없으면 새로 만듦
    if target is None:
        target = RecordExchange(exchange_no=ex_no)
        rec.exchanges.append(target)

    # 필드 적용
    if "exchange_time" in p and p["exchange_time"] is not None:
        target.exchange_time = parse_time(p["exchange_time"])

    if "drain_volume" in p and p["drain_volume"] is not None:
        dv = int(p["drain_volume"])
        vrng(0 <= dv <= 6000, "배액량 0~6000 g")
        target.drain_volume = dv

    if "fill_volume" in p and p["fill_volume"] is not None:
        fv = int(p["fill_volume"])
        vrng(0 <= fv <= 6000, "주입액 중량 0~6000 g")
        target.fill_volume = fv

    if "fill_concentration" in p and p["fill_concentration"] is not None:
        fc = float(p["fill_concentration"])
        vrng(0 <= fc <= 100, "주입액 농도 0~100 %")
        target.fill_concentration = fc

    return target

# 일일 + 회차 패치 적용
def apply_patch(rec: Record, p: Dict[str, Any]) -> None:
    if not isinstance(p, dict):
        raise HTTPException(status_code=400, detail="patch payload는 dict여야 합니다.")

    # 1) 일일 공통 먼저 적용
    apply_record_patch(rec, p)

    # 2-A) 회차 배치 업데이트: {"exchanges": [ {...}, {...} ]}
    if "exchanges" in p and p["exchanges"] is not None:
        ex_list = p["exchanges"]
        if not isinstance(ex_list, list):
            raise HTTPException(status_code=400, detail="exchanges는 리스트여야 합니다.")

        seen = set()
        for ex in ex_list:
            if not isinstance(ex, dict):
                raise HTTPException(status_code=400, detail="exchanges 항목은 dict여야 합니다.")
            if "exchange_no" not in ex or ex["exchange_no"] is None:
                raise HTTPException(status_code=400, detail="각 회차에는 exchange_no가 필요합니다.")

            ex_no = int(ex["exchange_no"])
            if ex_no in seen:
                raise HTTPException(status_code=400, detail=f"회차 번호 중복: {ex_no}")
            seen.add(ex_no)

            # 각 회차 패치를 upsert
            upsert_exchange(rec, ex)

    # 2-B) 회차 단건 업데이트: 단일 dict에 회차 관련 키가 들어온 경우
    else:
        exchange_keys = {"exchange_no", "exchange_time", "drain_volume", "fill_volume", "fill_concentration"}
        if any(k in p for k in exchange_keys):
            upsert_exchange(rec, p)


# 에이전트: 한국어 텍스트 → patch dict
#  - 공통 + 회차 키 동시 추출
def agent_text_to_patch(text: str) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    t = text or ""

    # 혈압 "125/78"
    m = re.search(r'(\d{2,3})\s*/\s*(\d{2,3})', t)
    if m:
        patch["systolic"] = int(m.group(1))
        patch["diastolic"] = int(m.group(2))

    # 시간 "09:30", "9.30", "9시 30분"
    m = re.search(r'\b([01]?\d|2[0-3])[:\.]\s?([0-5]?\d)\b', t)
    if m:
        h, mi = m.groups()
        patch["exchange_time"] = f"{int(h):02d}:{int(mi):02d}"

    # 체중 "61.5kg"
    m = re.search(r'(\d{2,3}(?:[.,]\d)?)\s*kg', t, re.IGNORECASE)
    if m:
        patch["weight"] = float(m.group(1).replace(",", "."))

    # 배액량 "2100 mL"
    m = re.search(r'(\d{3,4})\s*mL', t, re.IGNORECASE)
    if m:
        patch["drain_volume"] = int(m.group(1))

    # 주입액 중량 "2000 g", "2,000g"
    m = re.search(r'(\d{3,4})\s*g\b', t, re.IGNORECASE)
    if m:
        patch["fill_volume"] = int(m.group(1).replace(",", ""))

    # 회차 "3회차" / "회차 3"
    m = re.search(r'(\d{1,2})\s*회차', t)
    if m:
        patch["exchange_no"] = int(m.group(1))
    else:
        m = re.search(r'회차\s*(\d{1,2})', t)
        if m:
            patch["exchange_no"] = int(m.group(1))

    # 혼탁도
    if "혼탁" in t:
        if any(k in t for k in ["없", "아니", "무", "맑", "투명", "깨끗"]):
            patch["turbidity"] = "없음"
        elif any(k in t for k in ["있", "이상", "탁", "흐림", "침전"]):
            patch["turbidity"] = "있음"

    # 소변 횟수: "소변 6회", "소변 5 번"
    m = re.search(r'소변\s*(\d{1,2})\s*(회|번)', t)
    if m:
        patch["urine_count"] = int(m.group(1))

    # 공복혈당: "공복혈당 95", "공복 110"
    m = re.search(r'(공복혈당|공복)\s*(\d{2,3})', t)
    if m:
        patch["fasting_glucose"] = int(m.group(2))

    # 주입액 농도: "농도 2.5", "2.5% 용액"
    m = re.search(r'(?:농도|dextrose|포도당)\s*([0-9.]{1,4})', t, re.IGNORECASE)
    if m:
        patch["fill_concentration"] = float(m.group(1))

    # Gemini 보조
    if patch or not gemini:
        return patch

    system = (
        "너는 복막투석 기록 업데이트 보조 에이전트야. "
        "사용자 발화에서 해당되는 키만 JSON으로 반환해줘. "
        "일일 공통 키: weight(float), systolic(int), diastolic(int), fasting_glucose(int), "
        "urine_count(int), turbidity('없음'|'있음'), notes(str). "
        "회차 키: exchange_no(int), exchange_time('HH:MM'), drain_volume(int), "
        "fill_volume(int), fill_concentration(float). "
        "없는 키는 포함하지 말고, 숫자는 단위 제거."
    )
    prompt = f"{system}\n\n사용자 발화: {text}\n\n응답 예시: {{\"systolic\":120,\"exchange_no\":1,\"exchange_time\":\"09:30\"}}"
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