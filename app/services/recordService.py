import re
from datetime import time as dtime, date
from typing import Dict, Any

from fastapi import HTTPException

from app.db_models.record import Record
from app.db_models.record_exchange import RecordExchange

# 공통 유틸
def vrng(cond: bool, msg: str):
    if not cond:
        raise HTTPException(status_code=400, detail=msg)

# "HH:MM" 파싱
def parse_time(s: str) -> dtime:
    s = (s or "").strip().replace("시", ":").replace(".", ":")
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", s)
    if not m:
        raise ValueError("시간은 HH:MM 형식이어야 합니다.")
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("시간 범위 오류(0~23시, 0~59분)")
    return dtime(hour=hh, minute=mm)

# 회차 정보 직렬화(dict)
def ex_to_dict(e: RecordExchange) -> Dict[str, Any]:
    return {
        "id": e.id,
        "exchange_no": e.exchange_no,
        "exchange_time": e.exchange_time.strftime("%H:%M") if e.exchange_time else None,
        "drain_volume": e.drain_volume,
        "fill_volume": e.fill_volume,
        "fill_concentration": e.fill_concentration,
        "uf": e.uf
    }

# 공통 정보 직렬화(dict)
def rec_to_dict(r: Record) -> Dict[str, Any]:
    return {
        "id": r.id,
        "record_date": r.record_date.strftime("%Y-%m-%d") if isinstance(r.record_date, date) else r.record_date,
        "record_dw": r.record_dw,
        "weight": r.weight,
        "systolic": r.systolic,
        "diastolic": r.diastolic,
        "fasting_glucose": r.fasting_glucose,
        "urine_count": r.urine_count,
        "turbidity": r.turbidity,
        "notes": r.notes,
        "total_uf": r.total_uf,
        "exchanges": [ex_to_dict(e) for e in (r.exchanges or [])],
    }

# 공통 정보 필드 패치
def apply_record_patch(rec: Record, p: Dict[str, Any]) -> None:
    if "record_date" in p and p["record_date"] is not None:
        rd = p["record_date"]
        if isinstance(rd, str):
            try:
                rec.record_date = date.fromisoformat(rd)
            except Exception:
                raise HTTPException(status_code=400, detail=f"record_date 형식 오류: {rd}")
        elif isinstance(rd, date):
            rec.record_date = rd

    if "record_dw" in p and p["record_dw"] is not None:
        dw = str(p["record_dw"])
        vrng(dw in {"월", "화", "수", "목", "금", "토", "일"}, "record_dw는 월~일 중 하나여야 합니다.")
        rec.record_dw = dw

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

    if "total_uf" in p and p["total_uf"] is not None:
        try:
            tu = int(p["total_uf"])
        except Exception:
            raise HTTPException(status_code=400, detail="total_uf는 정수여야 합니다.")
        vrng(-5000 <= tu <= 5000, "total_uf 범위 오류(±5000)")
        rec.total_uf = tu

# 회차 정보 upsert
def upsert_exchange(rec: Record, p: Dict[str, Any]) -> RecordExchange:
    vrng("exchange_no" in p and p["exchange_no"] is not None, "회차(개별)에는 exchange_no가 필요합니다.")
    ex_no = int(p["exchange_no"])
    vrng(1 <= ex_no <= 12, "회차는 1~12 범위")

    # 기존 찾기
    target = None
    if rec.exchanges:
        for e in rec.exchanges:
            if e.exchange_no == ex_no:
                target = e
                break

    # 없으면 신규
    if target is None:
        target = RecordExchange(exchange_no=ex_no)
        rec.exchanges.append(target)

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

    if "uf" in p and p["uf"] is not None:
        uf = int(p["uf"])
        vrng(-500 <= uf <= 500, "제수량 -500~500 g")
        target.uf = uf

    return target