from typing import List, Optional

from pydantic import Field, ConfigDict

from app.models.record_schemas import ORMBase
from datetime import date


class WeightUfPoint(ORMBase):
    record_date: date = Field(..., description="기록 날짜")
    weight: float | None = Field(None, gt=0, description="체중 (kg)")
    total_uf: int | None = Field(None, description="일별 제수량 합계 (mL)")

class WeeklyAverageData(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "weight_avg": 62.5,
                "total_uf_avg": 600
            }
        }
    )
    weight_avg: Optional[float] = Field(None, description="주간 평균 체중")
    total_uf_avg: Optional[float] = Field(None, description="주간 평균 제수량 합계")

class WeeklyAverageResponse(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "start_date": "2025-11-17",
                "end_date": "2025-11-23",
                "data": {
                    "weight_avg": 62.5,
                    "total_uf_avg": 600
                }
            }
        }
    )
    start_date: date = Field(..., description="주간 시작일 (월요일)")
    end_date: date = Field(..., description="주간 종료일 (일요일)")
    data: WeeklyAverageData = Field(..., description="주간 기록 데이터 평균 값")


class BloodPressureSummary(ORMBase):
    avg_systolic: float | None = Field(None, description="최근 7일간 기록된 최고 혈압의 평균값")
    avg_diastolic: float | None = Field(None, description="최근 7일간 기록된 최저 혈압의 평균값")
    max_systolic: int | None = Field(None, description="최근 7일간 기록된 최고 혈압 중 가장 높은 값")
    max_diastolic: int | None = Field(None, description="최근 7일간 기록된 최저 혈압 중 가장 높은 값")
    min_systolic: int | None = Field(None, description="최근 7일간 기록된 최고 혈압 중 가장 낮은 값")
    min_diastolic: int | None = Field(None, description="최근 7일간 기록된 최저 혈압 중 가장 낮은 값")

class Last7DaysStats(ORMBase):
    points: List[WeightUfPoint]
    bp_summary: BloodPressureSummary