from datetime import date, timedelta
from typing import List

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.db_models import Record
from app.models.stats_schemas import WeightUfPoint


# 최근 7일 동안의 일별 체중 & 일별 제수량 추이 조회
def get_weight_uf_last_7_days(
    db: Session,
    user_id: int,
) -> List[WeightUfPoint]:
    today = date.today()
    start_date = today - timedelta(days=6)  # 오늘 포함 최근 7일

    # 1. 최근 7일 사이의 기록만 한 번에 가져오기
    rows = (
        db.query(Record)
        .filter(
            and_(
                Record.user_id == user_id,
                Record.record_date >= start_date,
                Record.record_date <= today,
            )
        )
        .order_by(Record.record_date.asc())
        .all()
    )

    # 2. 날짜별로 접근하기 쉽게 dict로 매핑
    record_by_date: dict[date, Record] = {
        r.record_date: r for r in rows
    }

    # 3. 최근 7일(과거 → 오늘 순)로 list 채우기
    result: List[WeightUfPoint] = []
    for offset in range(6, -1, -1):  # 6일 전 → 오늘
        d = today - timedelta(days=offset)
        rec = record_by_date.get(d)

        if rec is not None:
            weight = rec.weight if rec.weight is not None else None
            total_uf = rec.total_uf if rec.total_uf is not None else None
        else:
            weight = None
            total_uf = None

        result.append(
            WeightUfPoint(
                record_date=d,
                weight=weight,
                total_uf=total_uf,
            )
        )

    return result