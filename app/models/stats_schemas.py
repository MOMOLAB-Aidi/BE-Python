from pydantic import Field

from app.models.record_schemas import ORMBase
from datetime import date


class WeightUfPoint(ORMBase):
    record_date: date = Field(..., description="기록 날짜")
    weight: float | None = Field(None, gt=0, description="체중 (kg), 기록 없으면 None")
    total_uf: int | None = Field(None, description="일별 제수량 합계 (mL), 기록 없으면 None")