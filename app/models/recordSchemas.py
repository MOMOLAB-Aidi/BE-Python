from datetime import datetime, date
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, ConfigDict, constr

# 오늘 기본값 예시 구성
today = datetime.now()
today_str = today.strftime("%Y-%m-%d")
time_str = today.strftime("%H:%M")
weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
today_dw = weekday_kr[today.weekday()]

# 입력되는 시간 형식: "HH:MM" 또는 "HH:MM:SS"
TimeStr = constr(pattern=r"^\d{2}:\d{2}(:\d{2})?$")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


DayWeekKR = Literal["월", "화", "수", "목", "금", "토", "일"]
Turbidity = Literal["없음", "있음"]


# 공통 정보 생성 스키마
class RecordCommonCreate(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "record_date": today_str,
                "record_dw": today_dw,
                "weight": 61.5,
                "systolic": 118,
                "diastolic": 72,
                "fasting_glucose": 95,
                "urine_count": 6,
                "turbidity": "없음",
                "notes": "환자의 상태 양호",
                "total_uf": 150
            }
        }
    )
    record_date: date = Field(..., description="YYYY-MM-DD")
    record_dw: DayWeekKR = Field(..., description="요일(월~일)")
    weight: float = Field(..., ge=20.0, le=300.0)
    systolic: int = Field(..., ge=70, le=240)
    diastolic: int = Field(..., ge=40, le=160)
    fasting_glucose: int = Field(..., ge=40, le=600)
    urine_count: int = Field(..., ge=0, le=50)
    turbidity: Turbidity = Field(..., description="혼탁도(없음/있음)")
    notes: Optional[str] = Field(None, max_length=2000)
    total_uf: Optional[int] = Field(None, ge=-5000, le=5000)


# 공통 정보 수정 스키마
class RecordCommonPatch(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "weight": 61.2,
                "turbidity": "있음",
                "notes": "복막액 약간 혼탁, 통증 없음",
                "total_uf": 600
            }
        }
    )
    record_date: Optional[date] = None
    record_dw: Optional[DayWeekKR] = None
    weight: Optional[float] = Field(None, ge=20.0, le=300.0)
    systolic: Optional[int] = Field(None, ge=70, le=240)
    diastolic: Optional[int] = Field(None, ge=40, le=160)
    fasting_glucose: Optional[int] = Field(None, ge=40, le=600)
    urine_count: Optional[int] = Field(None, ge=0, le=50)
    turbidity: Optional[Turbidity] = None
    notes: Optional[str] = Field(None, max_length=2000)
    total_uf: Optional[int] = Field(None, ge=-5000, le=5000)


# 회차 정보 생성 스키마
class RecordExchangeCreate(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exchange_no": 1,
                "exchange_time": "09:00",
                "drain_volume": 2100,
                "fill_volume": 2000,
                "fill_concentration": 2.5,
                "uf": 100
            }
        }
    )
    exchange_no: int = Field(..., ge=1, le=5, description="구분(회차)")
    exchange_time: TimeStr = Field(..., description="HH:MM 또는 HH:MM:SS")
    drain_volume: int = Field(..., ge=0, le=6000)
    fill_volume: int = Field(..., ge=0, le=6000)
    fill_concentration: float = Field(..., ge=0, le=100, description="예: 1.5, 2.5, 4.25")
    uf: int = Field(..., ge=-500, le=500, description="제수량(-500~500)")


# 회차 정보 생성 요청 스키마 (리스트)
class RecordExchangeCreateList(ORMBase):
    exchanges: List[RecordExchangeCreate] = Field(..., description="생성할 회차 기록 리스트")


# 회차 정보 수정 스키마
class RecordExchangePatch(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exchange_time": "10:30",
                "drain_volume": 2200
            }
        }
    )
    exchange_no: Optional[int] = Field(None, ge=1, le=5, description="구분(회차)")
    exchange_time: Optional[TimeStr] = Field(None, description="HH:MM 또는 HH:MM:SS")
    drain_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_concentration: Optional[float] = Field(None, ge=0, le=100)
    uf: Optional[int] = Field(None, ge=-500, le=500)


# 회차 정보 수정 요청 스키마 (리스트)
class RecordExchangeUpdateList(ORMBase):
    # 단일 API 요청에 포함될 회차 리스트
    exchanges: List[RecordExchangePatch] = Field(..., description="수정할 회차 기록 리스트")


class WeeklyAverageData(BaseModel):
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

class WeeklyAverageResponse(BaseModel):
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
