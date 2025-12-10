import hashlib
import logging
from typing import List

from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, Response, status, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from app.core.db import get_db

from app.db_models.record import Record
from app.db_models.user import User

from app.core.auth import get_current_active_user as AuthTokenDep
from app.models.record_schemas import \
    RecordCreate, RecordPatch, TodayExchangeSummary
from app.services.ocr_service import upload_to_gcs, ocr_bytes_to_pdrecord_json, delete_from_gcs, OcrError, \
    download_from_gcs
from app.services.record_service import rec_to_dict, \
    get_latest_records, delete_record, \
    create_record_with_exchanges, update_record_with_exchanges, get_today_exchange_summary


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/api/v1/records/today-summary",
    tags=["복막투석기록"],
    summary="오늘 날짜의 기록 교환 요약",
    description="오늘 날짜의 기록 교환 완료 회차 수와 제수량 합계, 그리고 제수량 계산값 합계와 불일치 여부를 반환합니다.",
    response_model=TodayExchangeSummary,
)
def api_get_today_exchange_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(AuthTokenDep),
):
    summary = get_today_exchange_summary(db=db, user_id=current_user.id)
    return summary


@router.post(
    "/api/v1/records",
    tags=["복막투석기록"],
    summary="기록 생성",
    description="복막투석 기록의 공통 정보와 회차별 정보를 한 번에 생성합니다.",
    status_code=status.HTTP_201_CREATED,
)
def create_record_route(
    payload: RecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(AuthTokenDep),
):
    p = payload.model_dump(exclude_unset=True)
    try:
        create_record_with_exchanges(db, p, user_id=current_user.id, unique_by_date=True)
        return Response(status_code=status.HTTP_201_CREATED)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="이미 해당 날짜에 기록이 존재합니다.")


# 모든 복막투석기록 조회 api (공통 + 회차)
@router.get(
    "/api/v1/records",
    tags=["복막투석기록"],
    summary="환자의 모든 기록 조회",
    description="특정 년도와 월에 해당하는 환자의 모든 투석기록을 조회합니다."
)
def get_records(
        year: int = Query(2025, ge=2000, description="조회할 기록의 연도"),
        month: int = Query(11, ge=1, le=12, description="조회할 기록의 월"),
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
) -> List[dict]:

    try:
        records = (
            db.query(Record)
            # Record와 exchanges를 미리 로드하여 N+1 쿼리 문제를 방지
            .options(joinedload(Record.exchanges))
            .filter(Record.user_id == current_user.id)
            .filter(func.extract('year', Record.record_date) == year)
            .filter(func.extract('month', Record.record_date) == month)
            .order_by(Record.record_date.desc())  # 날짜 순으로 정렬
            .all()
        )
    except SQLAlchemyError as e:
        logging.exception("기록 목록 조회 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="기록 목록 조회 중 서버 오류가 발생했습니다.",
        ) from e

    if not records:
        return []

    # 조회된 Record 객체 리스트를 딕셔너리 리스트로 변환하여 반환
    return [rec_to_dict(rec) for rec in records]


@router.get(
    "/api/v1/records/latest",
    tags=["복막투석기록"],
    summary="환자의 가장 최근 3개의 기록 조회",
    description="환자의 가장 최근 3개의 기록을 조회합니다."
)
def get_latest_records_routes(
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
) -> List[dict]:

    try:
        records = get_latest_records(db, current_user.id)

    except SQLAlchemyError as e:
        logging.exception("최신 기록 목록 조회 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="최신 기록 목록 조회 중 서버 오류가 발생했습니다.",
        ) from e

    if not records:
        return []

    # 조회된 Record 객체 리스트를 딕셔너리 리스트로 변환하여 반환
    return [rec_to_dict(rec) for rec in records]


@router.post(
    "/api/v1/records/ocr",
    tags=["복막투석기록-ocr"],
    summary="OCR 인식 후 텍스트 추출",
    description="이미지 파일을 업로드하면 OCR을 수행하여 구조화된 JSON과 GCS 경로를 반환합니다.",
)
def ocr_temp(
    file: UploadFile = File(...),
    current_user: User = Depends(AuthTokenDep),
):
    try:
        raw = file.file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="빈 파일입니다.")

        # 사용자 해시값 생성
        user_hash = hashlib.sha256(str(current_user.id).encode()).hexdigest()[:16]

        # GCS에 이미지 업로드 (추후에 record 삭제하면 gcs_path 컬럼에 담긴 경로 삭제 -> GCS에서 해당 이미지 또한 삭제)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        content_type = file.content_type or "image/jpeg"
        ext = "jpg"

        if "png" in content_type.lower():
            ext = "png"
            content_type = "image/png"
        elif "jpeg" in content_type.lower() or "jpg" in content_type.lower():
            ext = "jpg"
            content_type = "image/jpeg"

        today_str = datetime.now().strftime("%Y%m%d")
        filename = f"ocr_temp_{timestamp}.{ext}"

        gcs_path_result = upload_to_gcs(
            file_bytes=raw,
            user_hash=user_hash,
            record_date=today_str,
            filename=filename,
            content_type=content_type,
        )

        try:
            ocr_data = ocr_bytes_to_pdrecord_json(
                file_bytes=raw,
                content_type=content_type,
            )
        except Exception:
            # OCR 실패 시 업로드된 GCS 파일 삭제
            try:
                delete_from_gcs(gcs_path_result)
            except Exception:
                logger.exception("GCS 정리 실패")
            raise

        # 프론트에서 호출 후 수기 작성 api로 저장
        return {
            "gcs_path": gcs_path_result,
            "ocr_data": ocr_data,
        }

    except OcrError as e:
        # OCR 관련 커스텀 에러
        status_code = 400 if e.is_client_error() else 500
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("OCR 처리 중 서버 내부 오류 발생")
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.") from e


@router.get(
    "/api/v1/records/ocr/image",
    tags=["복막투석기록-ocr"],
    summary="OCR 이미지 다운로드",
    description="gcs_path에 해당하는 OCR 이미지를 반환합니다.",
)
def get_ocr_image(
    gcs_path: str = Query(..., description="GCS 내부 경로"),
    current_user: User = Depends(AuthTokenDep),
):
    try:
        # 경로가 현재 사용자의 경로인지 검증
        user_hash = hashlib.sha256(str(current_user.id).encode()).hexdigest()[:16]
        if not gcs_path.startswith(f"users/{user_hash}/"):
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

        # GCS에서 실제 바이트 다운로드
        file_bytes = download_from_gcs(gcs_path)

        content_type = "image/jpeg"
        if gcs_path.lower().endswith(".png"):
            content_type = "image/png"

        return Response(content=file_bytes, media_type=content_type)
    except HTTPException:
        raise
    except OcrError as e:
        status_code = 400 if e.is_client_error() else 500
        raise HTTPException(status_code=status_code, detail=str(e)) from e
    except Exception as e:
        logger.exception("이미지 다운로드 실패")
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.") from e


@router.patch(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록"],
    summary="기록 수정",
    description="복막투석 기록의 공통 정보와 회차별 정보를 한 번에 부분 수정합니다.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={204: {"description": "성공입니다"}},
)
def patch_record_route(
    rec_id: int,
    payload: RecordPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(AuthTokenDep),
):
    p = payload.model_dump(exclude_unset=True)
    try:
        update_record_with_exchanges(db=db, rec_id=rec_id, p=p, user_id=current_user.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="데이터 무결성 오류가 발생했습니다.") from None


# 특정 복막투석기록 조회 api (공통 + 회차)
@router.get(
    "/api/v1/records/{rec_id}",
    tags=["복막투석기록"],
    summary="환자의 특정 기록 조회",
    description="특정 투석기록(공통 + 회차 전체)을 조회합니다."
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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("기록 삭제 중 서버 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="기록 삭제 중 서버 오류가 발생했습니다.",
        ) from e