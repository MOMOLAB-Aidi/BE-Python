import logging
import uuid

from fastapi import Depends, HTTPException, APIRouter, status, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from starlette.responses import StreamingResponse
from starlette.status import HTTP_201_CREATED

from app.core.db import get_db

from app.db_models.user import User

from app.core.auth import get_current_active_user as AuthTokenDep
from app.models.consult_schemas import SessionStartResponse, ChatRequest, SessionEndResponse, \
    SessionEndRequest, ConsultMessage, ConsultSession, ConsultSessionSummaryRow
from app.services.consult_service import start_new_session, get_session_status, get_agent_response_stream, end_session, \
    get_consult_history, get_consult_history_detail, delete_consult_session, summarize_consult_session


router = APIRouter()
logger = logging.getLogger(__name__)


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
    "/api/v1/consults",
    tags=["에이전트 상담"],
    summary="전체 상담 기록 목록 조회",
    description="세션별 상담 이력을 하나씩 묶어 전체 상담 기록 목록을 조회합니다. 각 세션에 요약이 존재하면 함께 반환됩니다.",
    response_model=list[ConsultSession],
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
        return [ConsultSession(**s) for s in summaries_dict]
    except SQLAlchemyError as e:
        logger.exception("상담 기록 조회 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="상담 기록 조회 중 서버 오류가 발생했습니다.",
        ) from e


@router.get(
    "/api/v1/consults/{session_id}",
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


@router.post(
    "/api/v1/consults/{session_id}/summary",
    tags=["에이전트 상담"],
    response_model=ConsultSessionSummaryRow,
    summary="특정 상담 세션 요약",
    description="특정 상담 세션이 끝난 후, 전체 상담 내용을 50자~120자 내로 요약하여 제공합니다.",
    status_code=HTTP_201_CREATED,
)
def create_consult_summary(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(AuthTokenDep),
):
    try:
        summary_text = summarize_consult_session(
            db=db,
            user_id=current_user.id,
            session_id=session_id,
        )

        return ConsultSessionSummaryRow(
            session_id=session_id,
            summary=summary_text,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("상담 요약 생성 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="상담 요약 생성 중 서버 오류가 발생했습니다.",
        ) from e
    except Exception as e:
        logger.exception("상담 요약 생성 중 예상치 못한 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="상담 요약 생성 중 서버 오류가 발생했습니다.",
        ) from e