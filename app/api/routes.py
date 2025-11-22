import hashlib
import logging
import uuid
from typing import List, Optional

from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, Response, status, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload
from datetime import date as _date, datetime, date

from starlette.responses import StreamingResponse

from app.core.db import get_db

from app.db_models.record import Record
from app.db_models.user import User

from app.core.auth import get_current_active_user as AuthTokenDep
from app.models.consult_schemas import SessionStartResponse, ChatRequest, SessionEndResponse, \
    SessionEndRequest
from app.models.record_schemas import WeeklyAverageResponse, WeeklyAverageData, RecordCommonCreate, RecordCommonPatch, \
    RecordExchangeCreateList, RecordExchangeUpdateList
from app.services.consult_service import start_new_session, get_session_status, get_agent_response_stream, end_session
from app.services.ocr_service import upload_to_gcs, ocr_bytes_to_pdrecord_json, delete_from_gcs, OcrError, \
    download_from_gcs
from app.services.record_service import get_weekly_average_records, create_record_common, rec_to_dict, \
    get_latest_records, apply_record_patch, create_exchanges_list, patch_exchanges_list, delete_record

router = APIRouter()

logger = logging.getLogger(__name__)


class RecordCreateResponse(BaseModel):
    id: int


@router.get("/api/v1/records/weekly-average",
            tags=["복막투석기록"],
            summary="주간 기록 데이터 평균 조회",
            description="특정 날짜가 포함된 주의 (월요일 ~ 일요일) 환자 기록 데이터의 평균을 계산하여 반환합니다.",
            response_model=WeeklyAverageResponse,
            )
def get_weekly_average(
        current_user: User = Depends(AuthTokenDep),
        target_date: Optional[date] = Query(None, description="지정하지 않으면 오늘 날짜 기준 주간을 사용합니다."), db: Session = Depends(get_db)
):
    try:
        effective_date = target_date or date.today()
        avg_data, start_date, end_date = get_weekly_average_records(db, current_user.id, effective_date)

        # Pydantic 모델로 변환하여 응답
        return WeeklyAverageResponse(
            start_date=start_date,
            end_date=end_date,
            data=WeeklyAverageData(**avg_data)
        )

    except SQLAlchemyError as e:
        logger.exception("주간 평균 계산 중 DB 오류 발생")
        raise HTTPException(status_code=500, detail="주간 평균 계산 중 서버 오류가 발생했습니다.") from e
    except Exception as e:
        logger.exception("주간 평균 계산 중 예상치 못한 오류 발생")
        raise HTTPException(status_code=500, detail="주간 평균 계산 중 서버 오류가 발생했습니다.") from e


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


MAX_EXCHANGES = 5

# 복막투석기록 회차 정보 생성 api
@router.post(
    "/api/v1/records/{rec_id}/exchanges",
    tags=["복막투석기록-회차"],
    summary="회차 정보 생성",
    description="특정 기록에 회차 정보를 생성합니다. 최대 5개까지 작성할 수 있습니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def create_record_exchange(
        rec_id: int,
        payload: RecordExchangeCreateList,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    exchange_list = [ex.model_dump(exclude_unset=True) for ex in payload.exchanges]
    create_exchanges_list(db, rec_id, exchange_list, user_id=current_user.id)

    db.commit()
    return Response(status_code=204)


# 복막투석기록 회차 정보 수정 api
@router.patch(
    "/api/v1/records/{rec_id}/exchanges",
    tags=["복막투석기록-회차"],
    summary="회차 정보 수정",
    description="특정 기록의 여러 회차 정보를 한 번에 수정합니다.",
    status_code=204,
    responses={204: {"description": "성공입니다"}},
)
def patch_record_exchange(
        rec_id: int,
        payload: RecordExchangeUpdateList,
        db: Session = Depends(get_db),
        current_user: User = Depends(AuthTokenDep)
):
    update_list = [ex.model_dump(exclude_unset=True) for ex in payload.exchanges]
    patch_exchanges_list(db, rec_id, update_list, user_id=current_user.id)

    db.commit()
    return Response(status_code=204)


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
        raise HTTPException(status_code=500, detail="기록 삭제 중 서버 오류가 발생했습니다.") from e


@router.post("/api/v1/consult/start",
     tags=["에이전트 상담"],
     summary="새로운 복막투석 상담 시작",
     description="새로운 복막투석 상담 세션을 시작하고 고유한 세션 ID를 발급합니다.",
     response_model=SessionStartResponse,
     status_code=status.HTTP_201_CREATED,
)
def start_chat_session(current_user: User = Depends(AuthTokenDep)):
    session_id = str(uuid.uuid4())

    # 세션 생성 로직 호출
    if start_new_session(current_user.id, session_id):
        return SessionStartResponse(
            session_id=session_id,
            message="안녕하세요! 복막투석 AI 상담사입니다. 투석 관리, 일반 지침, 건강 상태 등에 대해 무엇이든 물어보세요."
        )
    else:
        # gemini 클라이언트 초기화 실패 시 500 에러 발생
        raise HTTPException(status_code=500, detail="상담 에이전트 서비스 초기화에 실패했습니다. 서버 로그를 확인해주세요.")



@router.post("/api/v1/consult/chat",
     tags=["에이전트 상담"],
     summary="에이전트 대화",
     description="세션 ID를 사용하여 에이전트와 대화를 나눕니다. Server-Sent Events(SSE) 형식으로 스트리밍 응답을 반환합니다.",
     responses = {
         200: {
            "description": "에이전트 응답 스트림",
            "content": {"text/event-stream": {"example": "응답 텍스트가 실시간으로 스트리밍됩니다."}}
         }
     }
)
def send_chat_message(request: ChatRequest, db: Session = Depends(get_db), current_user: User = Depends(AuthTokenDep)):

    # 세션 활성화 상태 확인
    if not get_session_status(current_user.id, request.session_id):
        raise HTTPException(
            status_code=404,
            detail="활성화된 세션을 찾을 수 없습니다. `/start`를 통해 세션을 시작해주세요."
        )

    # agentService를 통해 응답 생성
    response_generator = get_agent_response_stream(db, current_user.id, request.session_id, request.message)

    return StreamingResponse(
        response_generator,
        media_type="text/event-stream"
    )

@router.post("/api/v1/consult/end",
     tags=["에이전트 상담"],
     summary="상담 종료",
     description="활성화된 세션을 종료하고 메모리에서 제거합니다.",
     response_model=SessionEndResponse,
)
def end_chat_session(request: SessionEndRequest, current_user: User = Depends(AuthTokenDep)):
    session_id = request.session_id

    if end_session(current_user.id, session_id):
        return SessionEndResponse(
            session_id=session_id,
            status="세션이 성공적으로 종료되었습니다. 이용해 주셔서 감사합니다."
        )
    else:
        # 종료할 세션이 메모리에 없거나 user_id가 소유자와 불일치할 경우 404 에러
        raise HTTPException(status_code=404, detail="종료할 활성화된 세션을 찾을 수 없습니다.")