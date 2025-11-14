import hashlib
from sysconfig import get_scheme_names

from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from datetime import date as _date, datetime

from starlette.responses import JSONResponse

from app.core.db import get_db

from app.db_models.record import Record
from app.db_models.record_exchange import RecordExchange
from app.db_models.user import User

from app.core.auth import get_current_active_user as AuthTokenDep

from app.models.recordSchemas import RecordCommonPatch, RecordCommonCreate, RecordExchangeCreate, RecordExchangePatch
from app.services.ocrService import OcrError, ocr_bytes_to_pdrecord_json, save_pdrecord_json, record_to_dict, \
    upload_to_gcs
from app.services.recordService import rec_to_dict, apply_record_patch, ex_to_dict, create_exchange, \
    create_record_common, patch_exchange, delete_record

router = APIRouter()


class RecordCreateResponse(BaseModel):
    id: int


# 복막투석기록 공통 정보 생성 api
@router.post(
    "/api/v1/records",
    tags=["복막투석기록-공통"],
    summary="공통 정보 생성",
    description="회차 없이 공통 정보만 생성합니다. 같은 날짜가 이미 있으면 409를 반환합니다.",
    status_code=status.HTTP_201_CREATED,
    response_model=RecordCreateResponse,
)
def create_record_common_route(
        payload: RecordCommonCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    p = payload.model_dump(exclude_unset=True)
    try:
        rec = create_record_common(db, p, user_id=current_user.id, unique_by_date=True)
        return RecordCreateResponse(id=rec.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="해당 날짜의 기록이 이미 존재합니다.")


# 복막투석기록 공통 정보 수정 api
@router.patch(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록-공통"],
    summary="공통 정보 수정",
    description="공통 정보만 부분 수정합니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def patch_record_common(
        rec_id: int,
        payload: RecordCommonPatch,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    if rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

    patch = payload.model_dump(exclude_unset=True)

    # record_date가 변경되는 경우, 동일 날짜의 다른 레코드가 있는지 검사
    if "record_date" in patch and patch["record_date"] is not None:
        new_date = patch["record_date"]
        if isinstance(new_date, str):
            new_date = _date.fromisoformat(new_date)
        if new_date != rec.record_date:
            exists = (
                db.query(Record.id)
                .filter(
                    Record.record_date == new_date,
                    Record.id != rec.id,
                    Record.user_id == current_user.id)
                .first()
            )
            if exists:
                raise HTTPException(status_code=409, detail=f"{new_date.isoformat()} 기록이 이미 존재합니다.")

    apply_record_patch(rec, patch, user_id=current_user.id)

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
def create_record_exchange(
        rec_id: int,
        payload: RecordExchangeCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    if rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="생성 권한이 없습니다.")

    p = payload.model_dump()
    create_exchange(rec, p, user_id=current_user.id)

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
def patch_record_exchange(
        rec_id: int,
        exchange_no: int,
        payload: RecordExchangePatch,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    if rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

    p = payload.model_dump(exclude_unset=True)
    p["exchange_no"] = p.get("exchange_no", exchange_no)

    patch_exchange(rec, p, user_id=current_user.id)

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
def get_record(
        rec_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    if rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="조회 권한이 없습니다.")
    rec = (
        db.query(Record)
        .options(joinedload(Record.exchanges))
        .filter(Record.id == rec_id)
        .one()
    )
    return rec_to_dict(rec)


# 특정 복막투석기록 회차 정보 조회
@router.get(
    "/api/v1/records/{rec_id}/exchanges/{exchange_id}",
    tags=["복막투석기록-회차"],
    summary="회차 단건 조회",
    description="특정 기록의 회차 중 교체 ID(RecordExchange.id)로 단건 조회합니다."
)
def get_record_exchange_by_id(
        rec_id: int,
        exchange_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    rec = db.get(Record, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")

    if rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="조회 권한이 없습니다.")

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


# 기록 삭제 api
@router.delete(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록"],
    summary="기록 삭제",
    description="특정 아이디의 기록을 삭제합니다. 연관된 회차 정보를 모두 삭제합니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def delete_record_route(
        rec_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    try:
        delete_record(db, rec_id, current_user.id)

        return Response(status_code=204)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 오류 발생: {str(e)}")


# 파일 업로드 -> OCR 텍스트 추출 -> JSON 반환 -> db 저장 api
@router.post(
    "/api/v1/ocr",
    tags=["복막투석기록"],
    summary="ocr 텍스트 추출 후 저장",
    description="파일을 업로드하면 OCR 기능으로 텍스트를 추출하여 db에 저장합니다."
)
def ocr_and_save(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    try:
        raw = file.file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="빈 파일입니다.")

        # 사용자 해시값 생성
        user_hash = hashlib.sha256(str(current_user.id).encode()).hexdigest()[:16]

        # 1. OCR만 처리: 409 에러가 발생했음에도 이미지가 저장되는 문제가 존재
        data = ocr_bytes_to_pdrecord_json(
            file_bytes=raw,
            content_type=file.content_type or "application/octet-stream"
        )

        # 2. DB 저장
        rec = save_pdrecord_json(data, db, user_id=current_user.id)

        # 3. GCS 업로드
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 파일 MIME 타입에 따라 확장자와 content_type 결정
        content_type = file.content_type or "image/jpeg"
        ext = "jpg"

        if "png" in content_type.lower():
            ext = "png"
            content_type = "image/png"
        elif "jpeg" in content_type.lower() or "jpg" in content_type.lower():
            ext = "jpg"
            content_type = "image/jpeg"

        filename = f"ocr_{rec.record_date}_{timestamp}.{ext}"

        gcs_path_result = upload_to_gcs(
            file_bytes=raw,
            user_hash=user_hash,
            record_date=rec.record_date.strftime("%Y%m%d"),
            filename=filename,
            content_type=content_type
        )

        rec.gcs_path = gcs_path_result
        db.add(rec)
        db.commit()

        # 관계 선로딩 후 스냅샷 반환 + 세션 종료 후 lazy-load 에러 방지
        rec = (
            db.query(type(rec))
            .options(joinedload(Record.exchanges))
            .filter_by(id=rec.id)
            .one()
        )

        return JSONResponse(record_to_dict(rec))

    except OcrError as e:
        status_code = 400 if e.is_client_error() else 500
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    except HTTPException:
        raise
    except ValueError as e:
        # save_pdrecord_json 내부 검증(필수값, 형식) 에러
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.") from e