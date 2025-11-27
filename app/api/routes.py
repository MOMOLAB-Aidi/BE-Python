import hashlib
import logging
import uuid
from typing import List, Optional

from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, Response, status, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, date

from starlette.responses import StreamingResponse

from app.core.db import get_db

from app.db_models.record import Record
from app.db_models.user import User

from app.core.auth import get_current_active_user as AuthTokenDep
from app.models.consult_schemas import SessionStartResponse, ChatRequest, SessionEndResponse, \
    SessionEndRequest, ConsultSessionSummary, ConsultMessage
from app.models.record_schemas import \
    RecordCreate, RecordPatch
from app.models.stats_schemas import WeightUfPoint, WeeklyAverageResponse, WeeklyAverageData, Last7DaysStats
from app.services.consult_service import start_new_session, get_session_status, get_agent_response_stream, end_session, \
    get_consult_history, get_consult_history_detail, delete_consult_session
from app.services.ocr_service import upload_to_gcs, ocr_bytes_to_pdrecord_json, delete_from_gcs, OcrError, \
    download_from_gcs
from app.services.record_service import get_weekly_average_records, rec_to_dict, \
    get_latest_records, delete_record, \
    create_record_with_exchanges, update_record_with_exchanges
from app.services.stats_service import get_weight_uf_last_7_days

router = APIRouter()

logger = logging.getLogger(__name__)


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


@router.post("/api/v1/consults/start",
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


@router.post("/api/v1/consults/chat",
     tags=["에이전트 상담"],
     summary="에이전트 대화",
     description="세션 ID를 사용하여 에이전트와 대화를 나눕니다. 응답은 text/plain 형식의 스트리밍으로 실시간 전달됩니다."
)
def send_chat_message(request: ChatRequest, db: Session = Depends(get_db), current_user: User = Depends(AuthTokenDep)):

    # 세션 활성화 상태 확인
    if not get_session_status(current_user.id, request.session_id):
        raise HTTPException(
            status_code=404,
            detail="활성화된 세션을 찾을 수 없습니다. `/start`를 통해 세션을 시작해주세요."
        )

    stream = get_agent_response_stream(
        db,
        current_user.id,
        request.session_id,
        request.message,
    )

    return StreamingResponse(
        stream,
        media_type="text/plain; charset=utf-8",
    )

@router.post("/api/v1/consults/end",
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


@router.get(
    "/api/v1/consults/history",
    tags=["에이전트 상담"],
    summary="전체 상담 기록 목록 조회",
    description="세션별 상담 이력을 하나씩 묶어 전체 상담 기록 목록을 조회합니다.",
    response_model=list[ConsultSessionSummary],
)
def get_consult_history_routes(
    skip: int = Query(0, ge=0, description="건너뛸 레코드 수"),
    limit: int = Query(50, ge=1, le=100, description="조회할 최대 레코드 수"),
    db: Session = Depends(get_db),
    current_user: User = Depends(AuthTokenDep),
):
    try:
        summaries_dict = get_consult_history(db, current_user.id, skip=skip, limit=limit)
        # dict → Pydantic 모델로 변환
        return [ConsultSessionSummary(**s) for s in summaries_dict]
    except SQLAlchemyError as e:
        logger.exception("상담 기록 조회 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="상담 기록 조회 중 서버 오류가 발생했습니다.",
        ) from e


@router.get(
    "/api/v1/consults/history/{session_id}",
    tags=["에이전트 상담"],
    summary="특정 상담 세션 상세 조회",
    description="특정 세션에 대해 상담 로그를 시간순으로 조회합니다.",
    response_model=list[ConsultMessage],
)
def get_consult_history_detail_routes(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(AuthTokenDep),
):
    try:
        logs = get_consult_history_detail(db, current_user.id, session_id)

        if not logs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="해당 상담 기록을 찾을 수 없습니다.",
            )

        return [
            ConsultMessage(
                role=log.role,
                content=log.content,
                created_at=log.created_at,
            )
            for log in logs
        ]
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("상담 기록 상세 조회 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="상담 기록 조회 중 서버 오류가 발생했습니다.",
        ) from e


@router.delete(
    "/api/v1/consults/{session_id}",
    tags=["에이전트 상담"],
    summary="특정 상담 기록 삭제",
    description="해당 세션의 모든 상담 메시지를 삭제합니다.",
    status_code=204,
)
def delete_consult_session_route(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(AuthTokenDep),
):
    try:
        deleted_count = delete_consult_session(db=db, user_id=current_user.id, session_id=session_id)

        if deleted_count == 0:
            raise HTTPException(
                status_code=404,
                detail="해당 세션의 상담 기록을 찾을 수 없습니다.",
            )

        return

    except HTTPException:
        raise

    except SQLAlchemyError as e:
        logger.exception("상담 기록 삭제 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="상담 기록 삭제 중 서버 오류가 발생했습니다.",
        ) from e


@router.get(
    "/api/v1/stats/last-7-days",
    response_model=Last7DaysStats,
    summary="최근 7일 체중/제수량 및 혈압 통계",
    description="최근 7일 동안의 체중과 제수량 추이, 혈압 통계를 반환합니다."
)
def get_last_7_days_stats(
    db: Session = Depends(get_db),
    current_user = Depends(AuthTokenDep),
):
    return get_weight_uf_last_7_days(db, current_user.id)