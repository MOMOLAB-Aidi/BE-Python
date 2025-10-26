from fastapi import Depends, HTTPException, APIRouter, status, UploadFile, File
from sqlalchemy.orm import Session
from datetime import date as _date

from starlette.responses import JSONResponse

from app.core.db import get_db
from app.db_models.record_exchange import RecordExchange

from app.db_models.record import Record

from app.models.recordSchemas import RecordCreate, RecordPatch
from app.services.ocrService import OcrError, ocr_bytes_to_pdrecord_json
from app.services.recordService import parse_time, rec_to_dict, apply_patch

router = APIRouter()

# 복막투석기록 생성 api
@router.post(
    "/api/v1/records",
    tags=["복막투석기록"],
    summary="기록 생성",
    description="복막투석기록(일일 공통 + 회차들)을 생성하는 API입니다.",
    status_code=status.HTTP_201_CREATED,
)
def create_record(payload: RecordCreate, db: Session = Depends(get_db)):
    try:
        d = _date.fromisoformat(payload.record_date) if payload.record_date else _date.today()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"record_date 오류: {e}")

    # 레코드 생성 (공통)
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
        total_uf=payload.total_uf
    )

    # 회차(개별) 생성
    seen_no = set()
    for ex in payload.exchanges or []:
        if ex.exchange_no in seen_no:
            raise HTTPException(status_code=400, detail=f"회차 번호 중복: {ex.exchange_no}")
        seen_no.add(ex.exchange_no)

        try:
            t = parse_time(ex.exchange_time)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"exchange_time 오류(회차 {ex.exchange_no}): {e}")

        rec.exchanges.append(
            RecordExchange(
                exchange_no=ex.exchange_no,
                exchange_time=t,
                drain_volume=ex.drain_volume,
                fill_volume=ex.fill_volume,
                fill_concentration=ex.fill_concentration,
                uf=ex.uf
            )
        )

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec_to_dict(rec)


# 특정 복막투석기록 조회 api
@router.get(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록"],
    summary="기록 조회",
    description="특정 복막투석기록(일일 공통 + 회차들)을 조회합니다.",
)
def get_record(rec_id: int, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")
    return rec_to_dict(rec)


# 복막투석기록 수정 api (부분 수정)
@router.patch(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록"],
    summary="기록 수정",
    description="복막투석기록을 부분 수정합니다. 회차 필드가 포함되면 해당 회차를 upsert합니다.",
)
def patch_record(rec_id: int, payload: RecordPatch, db: Session = Depends(get_db)):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    patch = payload.model_dump(exclude_unset=True)
    # apply_patch가 일일 공통 + 회차 upsert를 함께 처리
    apply_patch(rec, patch)

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec_to_dict(rec)


# 파일 업로드 -> OCR 텍스트 추출 -> JSON 반환 api
@router.post(
    "/api/v1/ocr",
    tags=["복막투석기록"],
    summary="ocr 텍스트 추출",
    description="파일을 업로드하면 OCR 기능으로 텍스트를 추출하여 JSON 형태로 반환합니다."
)
def ocr_to_text(file: UploadFile = File(...)):
    try:
        raw = file.file.read()

        data = ocr_bytes_to_pdrecord_json(
            file_bytes=raw,
            content_type=file.content_type or "application/octet-stream",
        )

        payload = {
            "filename": file.filename or "",
            "content_type": file.content_type or "",
            "size_bytes": len(raw),
            "model": "gemini-2.5-flash",
            "result": data,   # 구조화된 값들
        }
        return JSONResponse(payload)
    except OcrError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 오류: {type(e).__name__}: {e}")