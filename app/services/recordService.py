import re
from datetime import time as dtime, date
from typing import Dict, Any, Optional  # Optional 추가

from fastapi import HTTPException

from app.db_models.record import Record
from app.db_models.record_exchange import RecordExchange

# =========================
# 공통 유틸 / 파서
# =========================

def vrng(cond: bool, msg: str):
    if not cond:
        raise HTTPException(status_code=400, detail=msg)

def parse_time(s: str) -> dtime:
    s = (s or "").strip().replace("시", ":").replace(".", ":")
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", s)
    if not m:
        raise ValueError("시간은 HH:MM 형식이어야 합니다.")
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("시간 범위 오류(0~23시, 0~59분)")
    return dtime(hour=hh, minute=mm)

# 범용: payload에 키가 있고 값이 None이 아닐 때만 fn을 적용해 target.attr에 대입
def _apply_if_present(
    target: Any,
    payload: Dict[str, Any],
    key: str,
    fn,  # value -> cast/validate -> return
    attr: Optional[str] = None
):
    if key in payload and payload[key] is not None:
        value = fn(payload[key])
        setattr(target, attr or key, value)

# =========================
# 검증 헬퍼 메소드
# =========================
def _as_int_in(v: Any, lo: int, hi: int, label: str) -> int:
    try:
        iv = int(v)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{label}는 정수여야 합니다.")
    vrng(lo <= iv <= hi, f"{label} 범위({lo}~{hi})")
    return iv

def _as_float_in(v: Any, lo: float, hi: float, label: str) -> float:
    try:
        fv = float(v)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{label}는 실수여야 합니다.")
    vrng(lo <= fv <= hi, f"{label} 범위({lo}~{hi})")
    return fv

# =========================
# 직렬화
# =========================

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

# =========================
# 공통 정보 패치
# =========================

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
        rec.weight = round(_as_float_in(p["weight"], 20.0, 300.0, "체중(kg)"), 1)

    if "systolic" in p and p["systolic"] is not None:
        rec.systolic = _as_int_in(p["systolic"], 70, 240, "수축기")

    if "diastolic" in p and p["diastolic"] is not None:
        rec.diastolic = _as_int_in(p["diastolic"], 40, 160, "이완기")

    if "fasting_glucose" in p and p["fasting_glucose"] is not None:
        rec.fasting_glucose = _as_int_in(p["fasting_glucose"], 40, 600, "공복혈당")

    if "urine_count" in p and p["urine_count"] is not None:
        rec.urine_count = _as_int_in(p["urine_count"], 0, 50, "소변 횟수")

    if "turbidity" in p and p["turbidity"] is not None:
        vrng(p["turbidity"] in {"없음", "있음"}, "turbidity 값 오류(없음/있음)")
        rec.turbidity = p["turbidity"]

    if "notes" in p and p["notes"] is not None:
        rec.notes = str(p["notes"])[:2000]

    if "total_uf" in p and p["total_uf"] is not None:
        rec.total_uf = _as_int_in(p["total_uf"], -5000, 5000, "total_uf")

# =========================
# 회차 공통 처리
# =========================

def _require_exchange_no(p: Dict[str, Any]) -> int:
    vrng("exchange_no" in p and p["exchange_no"] is not None, "회차(개별)에는 exchange_no가 필요합니다.")
    ex_no = int(p["exchange_no"])
    vrng(1 <= ex_no <= 12, "회차는 1~12 범위")
    return ex_no

def _apply_exchange_fields(target: RecordExchange, p: Dict[str, Any]) -> None:
    _apply_if_present(target, p, "exchange_time", lambda v: parse_time(v))
    _apply_if_present(target, p, "drain_volume", lambda v: _as_int_in(v, 0, 6000, "배액량"))
    _apply_if_present(target, p, "fill_volume",  lambda v: _as_int_in(v, 0, 6000, "주입액 중량"))
    _apply_if_present(target, p, "fill_concentration", lambda v: _as_float_in(v, 0.0, 100.0, "주입액 농도(%)"))
    _apply_if_present(target, p, "uf", lambda v: _as_int_in(v, -500, 500, "제수량"))

def find_exchange(rec: Record, exchange_no: int) -> Optional[RecordExchange]:
    if not rec.exchanges:
        return None
    for e in rec.exchanges:
        if e.exchange_no == exchange_no:
            return e
    return None

# 존재하는 회차만 수정
def patch_exchange(rec: Record, p: Dict[str, Any]) -> RecordExchange:
    ex_no = _require_exchange_no(p)
    target = find_exchange(rec, ex_no)
    if target is None:
        raise HTTPException(status_code=404, detail=f"{ex_no}회차가 존재하지 않습니다.")
    _apply_exchange_fields(target, p)
    return target

def create_exchange(rec: Record, p: Dict[str, Any]) -> RecordExchange:
    ex_no = _require_exchange_no(p)
    if find_exchange(rec, ex_no) is not None:
        raise HTTPException(status_code=409, detail=f"{ex_no}회차가 이미 존재합니다.")

    target = RecordExchange(exchange_no=ex_no)
    _apply_exchange_fields(target, p)

    rec.exchanges = (rec.exchanges or [])
    rec.exchanges.append(target)
    return target
