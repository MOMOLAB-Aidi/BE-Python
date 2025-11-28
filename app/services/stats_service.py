from datetime import date, timedelta
from typing import List

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.db_models import Record
from app.models.stats_schemas import WeightUfPoint, BloodPressureSummary, Last7DaysStats


# 최근 7일 동안의 일별 체중 & 일별 제수량 추이 조회
def get_weight_uf_last_7_days(
    db: Session,
    user_id: int,
) -> Last7DaysStats:
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
    record_by_date: dict[date, Record] = { r.record_date: r for r in rows }

    points: List[WeightUfPoint] = []
    for offset in range(6, -1, -1):  # 6일 전 → 오늘
        d = today - timedelta(days=offset)
        rec = record_by_date.get(d)

        if rec is not None:
            weight = rec.weight if rec.weight is not None else None
            total_uf = rec.total_uf if rec.total_uf is not None else None
        else:
            weight = None
            total_uf = None

        points.append(
            WeightUfPoint(
                record_date=d,
                weight=weight,
                total_uf=total_uf,
            )
        )

    # 3. 혈압 통계 계산 (최근 7일 전체 기준)
    bp_values: list[tuple[int, int]] = []
    for r in rows:
        if r.systolic is not None and r.diastolic is not None:
            bp_values.append((r.systolic, r.diastolic))

    if bp_values:
        # 평균 및 최고/최저 (수축기·이완기 각각에 대해 계산)
        systolic_values = [s for s, _ in bp_values]
        diastolic_values = [d for _, d in bp_values]

        avg_systolic = sum(systolic_values) / len(systolic_values)
        avg_diastolic = sum(diastolic_values) / len(diastolic_values)

        max_systolic = max(systolic_values)
        max_diastolic = max(diastolic_values)
        min_systolic = min(systolic_values)
        min_diastolic = min(diastolic_values)

        bp_summary = BloodPressureSummary(
            avg_systolic = avg_systolic,
            avg_diastolic = avg_diastolic,
            max_systolic = max_systolic,
            max_diastolic = max_diastolic,
            min_systolic = min_systolic,
            min_diastolic = min_diastolic,
        )
    else:
        bp_summary = BloodPressureSummary(
            avg_systolic=None,
            avg_diastolic=None,
            max_systolic=None,
            max_diastolic=None,
            min_systolic=None,
            min_diastolic=None,
        )

    return Last7DaysStats(
        points=points,
        bp_summary=bp_summary,
    )