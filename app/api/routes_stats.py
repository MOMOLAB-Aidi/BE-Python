import logging

from fastapi import Depends, HTTPException, APIRouter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db

from app.core.auth import get_current_active_user as AuthTokenDep
from app.models.stats_schemas import Last7DaysStats, Last7DaysAverageResponse
from app.services.stats_service import get_weight_uf_last_7_days, get_last_7_days_average_records

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get(
    "/api/v1/stats/last-7-days",
    tags=["통계"],
    summary="최근 7일 체중/제수량 및 혈압 통계",
    description="최근 7일 동안의 체중과 제수량 추이, 혈압 통계를 반환합니다.",
    response_model=Last7DaysStats
)
def get_last_7_days_stats(
    db: Session = Depends(get_db),
    current_user = Depends(AuthTokenDep),
):
    try:
        return get_weight_uf_last_7_days(db, current_user.id)
    except SQLAlchemyError as e:
        logger.exception("최근 7일 통계 조회 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="최근 7일 통계 조회 중 서버 오류가 발생하였습니다.",
        ) from e


@router.get(
    "/api/v1/stats/last-7-days-average",
    tags=["통계"],
    summary="최근 7일 기록 평균 체중/제수량 합계",
    description="최근 7일 동안의 체중과 제수량 합계의 평균을 반환합니다.",
    response_model=Last7DaysAverageResponse,
)
def get_last7days_average(
    db: Session = Depends(get_db),
    current_user = Depends(AuthTokenDep),
):
    try:
        return get_last_7_days_average_records(db, current_user.id)
    except SQLAlchemyError as e:
        logger.exception("최근 7일 평균 통계 조회 중 DB 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="최근 7일 평균 통계 조회 중 서버 오류가 발생하였습니다.",
        ) from e
    except Exception as e:
        logger.exception("최근 7일 평균 통계 조회 중 예상치 못한 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="최근 7일 평균 통계 조회 중 서버 오류가 발생하였습니다.",
        ) from e