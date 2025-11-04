from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, Response
from sqlalchemy import asc
from sqlalchemy.orm import Session, joinedload
from datetime import date as _date

from starlette.responses import JSONResponse

from app.core.db import get_db

from app.db_models.record import Record
from app.db_models.record_exchange import RecordExchange

from app.models.recordSchemas import RecordCommonPatch, RecordCommonCreate, RecordExchangeCreate, RecordExchangePatch
from app.services.ocrService import OcrError, ocr_bytes_to_pdrecord_json, save_pdrecord_json, _record_to_dict
from app.services.recordService import rec_to_dict, apply_record_patch, upsert_exchange, ex_to_dict

router = APIRouter()


# 복막투석기록 공통 정보 생성 api
@router.post(
    "/api/v1/records",
    tags=["복막투석기록-공통"],
    summary="공통 정보 생성",
    description="회차 없이 공통 정보만 생성합니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def create_record_common(payload: RecordCommonCreate, db: Session = Depends(get_db)):
    d = payload.record_date or _date.today()

    rec = Record(
        record_date=d,
        record_dw=payload.record_dw,
        weight=payload.weight,
        systolic=payload.systolic,
        diastolic=payload.diastolic,
        fasting_glucose=payload.fasting_glucose,
        urine_count=payload.urine_count,
        turbidity=payload.turbidity,
        notes=payload.notes,
        total_uf=payload.total_uf, # 합계는 선택 입력(후입력 가능)
    )

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return Response(status_code=204)

# 복막투석기록 공통 정보 수정 api
@router.patch(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록-공통"],
    summary="공통 정보 수정",
    description="공통 정보만 부분 수정합니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def patch_record_common(rec_id: int, payload: RecordCommonPatch, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    patch = payload.model_dump(exclude_unset=True)
    apply_record_patch(rec, patch)

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return Response(status_code=204)

# 복막투석기록 회차 정보 생성 api
@router.post(
    "/api/v1/records/{rec_id}/exchanges",
    tags=["복막투석기록-회차"],
    summary="회차 정보 생성",
    description="특정 기록에 회차 정보를 생성합니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def upsert_record_exchange(rec_id: int, payload: RecordExchangeCreate, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    p = payload.model_dump()
    upsert_exchange(rec, p)

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return Response(status_code=204)

# 복막투석기록 회차 정보 수정 api
@router.patch(
    "/api/v1/records/{rec_id}/exchanges/{exchange_no}",
    tags=["복막투석기록-회차"],
    summary="회차 정보 수정",
    description="특정 기록의 특정 회차 정보를 수정합니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def patch_record_exchange(rec_id: int, exchange_no: int, payload: RecordExchangePatch, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    p = payload.model_dump(exclude_unset=True)
    p["exchange_no"] = p.get("exchange_no", exchange_no)

    upsert_exchange(rec, p)

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return Response(status_code=204)

# 특정 복막투석기록 조회 api (공통 + 회차)
@router.get(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록"],
    summary="전체 기록 조회",
    description="특정 복막투석기록(공통 + 회차 전체)을 조회합니다."
)
def get_record(rec_id: int, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")
    rec = (
        db.query(Record)
        .options(joinedload(Record.exchanges))
        .filter(Record.id == rec_id)
        .one()
    )
    return rec_to_dict(rec)

# 특정 복막투석기록 조회 (공통)
@router.get(
    "/api/v1/records/{rec_id}/common",
    tags=["복막투석기록-공통"],
    summary="공통 정보 조회",
    description="특정 기록(rec_id)의 공통정보를 조회합니다."
)
def get_record_common(rec_id: int, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    return {
        "id": rec.id,
        "record_date": rec.record_date,
        "record_dw": rec.record_dw,
        "weight": rec.weight,
        "systolic": rec.systolic,
        "diastolic": rec.diastolic,
        "fasting_glucose": rec.fasting_glucose,
        "urine_count": rec.urine_count,
        "turbidity": rec.turbidity,
        "notes": rec.notes,
        "total_uf": rec.total_uf
    }

# 특정 복막투석기록의 회차정보 목록 조회
@router.get(
    "/api/v1/records/{rec_id}/exchanges",
    tags=["복막투석기록-회차"],
    summary="회차 목록 조회",
    description="특정 기록(rec_id)의 회차 목록을 조회합니다."
)
def list_record_exchanges(rec_id: int, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    # 같은 기록에 속한 회차만 정렬해서 반환
    rows = (
        db.query(RecordExchange)
        .filter(RecordExchange.record_id == rec_id)
        .order_by(asc(RecordExchange.exchange_no))
        .all()
    )
    return [ex_to_dict(e) for e in rows]

# 특정 복막투석기록 회차 정보 조회
@router.get(
    "/api/v1/records/{rec_id}/exchanges/{exchange_id}",
    tags=["복막투석기록-회차"],
    summary="회차 단건 조회",
    description="특정 기록의 회차 중 교체 ID(RecordExchange.id)로 단건 조회합니다."
)
def get_record_exchange_by_id(rec_id: int, exchange_id: int, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    row = (
        db.query(RecordExchange)
        .filter(
            RecordExchange.record_id == rec_id,
            RecordExchange.id == exchange_id
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="해당 회차를 찾을 수 없습니다.")
    return ex_to_dict(row)


# 파일 업로드 -> OCR 텍스트 추출 -> JSON 반환 -> db 저장 api
@router.post(
    "/api/v1/ocr",
    tags=["복막투석기록"],
    summary="ocr 텍스트 추출 후 저장",
    description="파일을 업로드하면 OCR 기능으로 텍스트를 추출하여 db에 저장합니다."
)
def ocr_and_save(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        raw = file.file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="빈 파일입니다.")

        # OCR → 구조화 JSON
        data = ocr_bytes_to_pdrecord_json(
            file_bytes=raw,
            content_type=file.content_type or "application/octet-stream",
        )

        # JSON → DB 저장/갱신
        rec = save_pdrecord_json(data, db)

        # 관계 선로딩 후 스냅샷 반환 + 세션 종료 후 lazy-load 에러 방지
        rec = (
            db.query(type(rec))
            .options(joinedload(Record.exchanges))
            .filter_by(id=rec.id)
            .one()
        )

        return JSONResponse(_record_to_dict(rec))

    except OcrError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        # save_pdrecord_json 내부 검증(필수값, 형식) 에러
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")