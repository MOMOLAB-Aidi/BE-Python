import re
from datetime import time as dtime, date, timedelta
from typing import Dict, Any, Optional, List, Tuple
from datetime import date as _date

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db_models.record import Record
from app.db_models.record_exchange import RecordExchange
from app.services.ocr_service import delete_from_gcs, OcrError


# =========================
# 공통 유틸 / 파서
# =========================

def vrng(cond: bool, msg: str):
    if not cond:
        raise HTTPException(status_code=400, detail=msg)

def parse_time(s: str) -> dtime:
    s = (s or "").strip().replace("시", ":").replace(".", ":")
    # HH:MM 또는 HH:MM:SS
    m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})(?::\s*(\d{2}))?\s*$", s)
    if not m:
        raise ValueError("시간은 HH:MM 또는 HH:MM:SS 형식이어야 합니다.")
    hh, mm = int(m.group(1)), int(m.group(2))
    ss = int(m.group(3)) if m.group(3) is not None else 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise ValueError("시간 범위 오류(0~23시, 0~59분, 0~59초)")
    return dtime(hour=hh, minute=mm, second=ss)


# 다음 회차 번호 계산
def _next_exchange_no(rec: Record) -> int:
    exists = [e.exchange_no for e in (rec.exchanges or [])]
    next_no = (max(exists) + 1) if exists else 1
    vrng(1 <= next_no <= 5, "최대 5회차까지 등록 가능합니다.")
    return next_no


# payload에 키가 있고 값이 None이 아닐 때만 fn을 적용해 target.attr에 대입
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


# 검증
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
        "gcs_path": r.gcs_path,
        "exchanges": [ex_to_dict(e) for e in (r.exchanges or [])],
    }


# 필수 값 체크
def _require_fields_for_create(rec: Record):
    vrng(rec.record_date is not None, "record_date는 필수입니다.")
    vrng(rec.record_dw in {"월","화","수","목","금","토","일"}, "record_dw는 월~일 중 하나여야 합니다.")
    vrng(rec.weight is not None, "weight는 필수입니다.")
    vrng(rec.systolic is not None, "systolic는 필수입니다.")
    vrng(rec.diastolic is not None, "diastolic는 필수입니다.")
    vrng(rec.fasting_glucose is not None, "fasting_glucose는 필수입니다.")
    vrng(rec.urine_count is not None, "urine_count는 필수입니다.")
    vrng(rec.turbidity in {"없음","있음"}, "turbidity는 '없음' 또는 '있음'이어야 합니다.")


# 공통 정보 생성용 객체 빌더
def create_record_common_obj(p: Dict[str, Any], user_id: int) -> Record:
    rec = Record(user_id=user_id)
    # 날짜 미지정 시 오늘
    if "record_date" not in p or p["record_date"] is None:
        p = {**p, "record_date": _date.today()}

    apply_record_patch(rec, p, user_id=user_id)
    _require_fields_for_create(rec)
    return rec


# 공통 정보 수정
def apply_record_patch(rec: Record, p: Dict[str, Any], user_id: int, check_ownership: bool = True) -> None:

    # 기록의 소유자와 현재 사용자 ID가 일치하는지 확인
    if check_ownership and rec.user_id != user_id:
        raise HTTPException(status_code=403, detail="기록을 수정할 권한이 없습니다.")

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
        rec.total_uf = _as_int_in(p["total_uf"], -5000, 5000, "제수량 합계")

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


# 환자의 가장 최근 3개의 기록 조회
def get_latest_records(db: Session, user_id: int) -> List[Record]:

    records = (
        db.query(Record)
        .options(joinedload(Record.exchanges))  # N+1 문제 방지
        .filter(Record.user_id == user_id)
        .order_by(Record.record_date.desc())
        .limit(3)
        .all()
    )

    return records

# 회차 정보 리스트 수정
def patch_exchanges_list(
        db: Session,
        rec_id: int,
        exchange_update_list: List[Dict[str, Any]],
        user_id: int
) -> Record:
    rec = (
        db.query(Record)
        .options(joinedload(Record.exchanges))
        .filter(Record.id == rec_id)
        .first()
    )

    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    # 소유권 검증
    if rec.user_id != user_id:
        raise HTTPException(status_code=403, detail="기록을 수정할 권한이 없습니다.")

    # 현재 기록의 회차들을 ID 기준으로 맵핑
    exchanges_map = {e.id: e for e in (rec.exchanges or [])}

    for update_data in exchange_update_list:
        exchange_id = update_data.get("id")

        if exchange_id is None:
            raise HTTPException(status_code=400, detail="회차 수정을 위해서는 'id'가 필수입니다.")

        target = exchanges_map.get(exchange_id)

        if target is None:
            raise HTTPException(status_code=404, detail=f"회차 ID {exchange_id}를 찾을 수 없습니다.")

        _apply_exchange_fields(target, update_data)

    db.add(rec)
    db.flush()
    return rec


# 기록 삭제
def delete_record(db: Session, rec_id: int, user_id: int) -> None:

    record = (
        db.query(Record)
        .filter(Record.id == rec_id)
        .one_or_none()
    )

    if not record:
        raise HTTPException(status_code=404, detail=f"기록 ID {rec_id}를 찾을 수 없습니다.")

    # 소유권 검증
    if record.user_id != user_id:
        raise HTTPException(status_code=403, detail="기록을 삭제할 권한이 없습니다.")

    # GCS 이미지 삭제
    if record.gcs_path:
        # GCS 삭제 실패 시 DB 트랜잭션도 함께 중단
        try:
            delete_from_gcs(record.gcs_path)
        except OcrError as e:
            raise HTTPException(
                status_code=500,
                detail=f"GCS 이미지 삭제(경로: {record.gcs_path})에 실패하여 DB 기록 삭제를 취소합니다. 잠시 후 다시 시도해 주세요."
            ) from e

    # record 삭제
    db.delete(record)
    db.commit()


# 기준 날짜를 포함하는 주의 (월요일 ~ 일요일) 환자 기록 데이터의 평균을 계산
def get_weekly_average_records(
    db: Session,
    user_id: int,
    target_date: date
) -> Tuple[Dict[str, Optional[float]], date, date]:

    # 주간 시작일(월요일) 및 종료일(일요일) 계산
    # target_date.weekday()는 월요일(0) ~ 일요일(6)
    days_to_monday = target_date.weekday()
    start_date = target_date - timedelta(days=days_to_monday)
    end_date = start_date + timedelta(days=6)

    # 데이터베이스 쿼리 및 평균 계산
    avg_results = db.query(
        func.avg(Record.weight).label('weight_avg'),
        func.avg(Record.total_uf).label('total_uf_avg')
    ).filter(
        Record.user_id == user_id,
        Record.record_date.between(start_date, end_date)
    ).first()

    # 초기 빈 딕셔너리 할당을 제거하고 if/else 블록에서 직접 할당을 보장
    avg_data: Dict[str, Optional[float]]

    if avg_results is not None and any(v is not None for v in avg_results):
        # 결과에 값이 있을 경우
        avg_data = {
            'weight_avg': avg_results.weight_avg,
            'total_uf_avg': avg_results.total_uf_avg
        }
    else:
        # 데이터가 없는 경우
        avg_data = {
            'weight_avg': None,
            'total_uf_avg': None
        }

    return avg_data, start_date, end_date


# 제수량 검증
def _validate_uf_consistency(rec: Record):
    if not rec.exchanges:
        vrng(False, "회차 정보가 최소 1개 이상 필요합니다.")

    for e in rec.exchanges:
        expected_uf = e.drain_volume - e.fill_volume
        vrng(
            e.uf == expected_uf,
            f"{e.exchange_no}회차 제수량이 '배액량 - 주입액 중량'과 일치하지 않습니다."
        )

    vrng(rec.total_uf is not None, "제수량 합계(total_uf)가 입력되어야 합니다.")
    sum_uf = sum(e.uf for e in rec.exchanges)
    vrng(
        sum_uf == rec.total_uf,
        "모든 회차 제수량의 합과 제수량 합계(total_uf)가 일치하지 않습니다."
    )


# 공통 정보 + 회차별 정보 한 번에 생성
def create_record_with_exchanges(
    db: Session,
    p: Dict[str, Any],
    user_id: int,
    *,
    unique_by_date: bool = True,
) -> Record:

    exchanges_payload: List[Dict[str, Any]] = p.get("exchanges") or []
    vrng(1 <= len(exchanges_payload) <= 5, "회차는 1~5개까지 입력할 수 있습니다.")

    # exchanges 키는 제거하고 공통 정보만 객체 생성에 사용
    common_payload = {k: v for k, v in p.items() if k != "exchanges"}

    # Record 객체 생성 (아직 commit X)
    rec = create_record_common_obj(common_payload, user_id=user_id)

    # 같은 날짜 중복 체크
    if unique_by_date:
        existing = (
            db.query(Record)
            .filter(Record.record_date == rec.record_date, Record.user_id == user_id)
            .one_or_none()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"{rec.record_date.isoformat()} 기록이 이미 존재합니다."
            )

    # 회차 객체들 생성 + 필드 적용
    rec.exchanges = rec.exchanges or []

    if len(exchanges_payload) > 5:
        raise HTTPException(status_code=400, detail="기록 하나당 최대 5개의 회차만 생성할 수 있습니다.")

    for idx, exchange_data in enumerate(exchanges_payload, start=1):
        # 새 기록이므로 1부터 순서대로 회차 번호 부여
        target = RecordExchange(
            exchange_no=idx,
            user_id=user_id,
        )
        _apply_exchange_fields(target, exchange_data)
        rec.exchanges.append(target)

    for e in rec.exchanges:
        expected_uf = e.drain_volume - e.fill_volume
        vrng(
            e.uf == expected_uf,
            f"{e.exchange_no}회차 제수량이 '배액량 - 주입액 중량'과 일치하지 않습니다."
        )

    sum_uf = sum(e.uf for e in rec.exchanges)
    vrng(
        sum_uf == rec.total_uf,
        "모든 회차 제수량의 합과 제수량 합계가 일치하지 않습니다."
    )

    _validate_uf_consistency(rec)

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# 공통 정보 + 회차별 정보 한 번에 수정
def update_record_with_exchanges(
    db: Session,
    rec_id: int,
    p: Dict[str, Any],
    user_id: int,
) -> Record:
    rec: Optional[Record] = (
        db.query(Record)
        .options(joinedload(Record.exchanges))
        .filter(Record.id == rec_id)
        .first()
    )

    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    if rec.user_id != user_id:
        raise HTTPException(status_code=403, detail="기록을 수정할 권한이 없습니다.")

    # payload 분리
    exchanges_payload: Optional[List[Dict[str, Any]]] = p.get("exchanges")
    common_patch = {k: v for k, v in p.items() if k != "exchanges"}

    # 날짜 변경 시 중복 검사
    if "record_date" in common_patch and common_patch["record_date"] is not None:
        new_date = common_patch["record_date"]
        if isinstance(new_date, str):
            new_date = _date.fromisoformat(new_date)

        if new_date != rec.record_date:
            exists = (
                db.query(Record.id)
                .filter(
                    Record.record_date == new_date,
                    Record.id != rec.id,
                    Record.user_id == user_id,
                )
                .first()
            )
            if exists:
                raise HTTPException(
                    status_code=409,
                    detail=f"{new_date.isoformat()} 기록이 이미 존재합니다."
                )

    if common_patch:
        apply_record_patch(rec, common_patch, user_id=user_id, check_ownership=False)

    # 회차 수정
    if exchanges_payload is not None:
        exchanges_map = {e.id: e for e in (rec.exchanges or [])}

        for update_data in exchanges_payload:
            exchange_id = update_data.get("id")
            if exchange_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="회차 수정을 위해서는 'id'가 필수입니다."
                )

            target = exchanges_map.get(exchange_id)
            if target is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"회차 ID {exchange_id}를 찾을 수 없습니다."
                )

            _apply_exchange_fields(target, update_data)

    _validate_uf_consistency(rec)

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec




