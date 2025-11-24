from app.models.record_schemas import ORMBase
from datetime import date


class WeightUfPoint(ORMBase):
    date: date
    weight: float | None  # 해당 날짜에 기록 없으면 None
    total_uf: int | None  # 해당 날짜에 기록 없으면 None