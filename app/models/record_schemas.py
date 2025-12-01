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
    weight: Optional[float] = Field(None, ge=30.0, le=200.0)
    systolic: Optional[int] = Field(None, ge=70, le=240)
    diastolic: Optional[int] = Field(None, ge=40, le=160)
    fasting_glucose: Optional[int] = Field(None, ge=40, le=600)
    urine_count: Optional[int] = Field(None, ge=0, le=30)
    turbidity: Optional[Turbidity] = None
    notes: Optional[str] = Field(None, max_length=2000)
    total_uf: Optional[int] = Field(None, ge=-2500, le=2500)


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
    exchange_no: Optional[int] = Field(None, ge=1, le=5, description="구분(회차)", json_schema_extra={"readOnly": True})
    exchange_time: TimeStr = Field(..., description="HH:MM 또는 HH:MM:SS")
    drain_volume: int = Field(..., ge=0, le=6000)
    fill_volume: int = Field(..., ge=0, le=6000)
    fill_concentration: float = Field(..., ge=0, le=100, description="예: 1.5, 2.5, 4.25")
    uf: int = Field(..., ge=-500, le=500, description="제수량(-500~500)")


class RecordCreate(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "record_date": "2025-11-24",
                "record_dw": "월",
                "weight": 55.8,
                "systolic": 120,
                "diastolic": 75,
                "fasting_glucose": 110,
                "urine_count": 5,
                "turbidity": "없음",
                "notes": "컨디션 양호, 특별한 증상 없음",
                "total_uf": 600,
                "exchanges": [
                    {
                        "exchange_time": "08:00",
                        "drain_volume": 2100,
                        "fill_volume": 2000,
                        "fill_concentration": 1.5,
                        "uf": 100
                    },
                    {
                        "exchange_time": "14:00",
                        "drain_volume": 2300,
                        "fill_volume": 2000,
                        "fill_concentration": 2.5,
                        "uf": 300
                    },
                    {
                        "exchange_time": "20:00",
                        "drain_volume": 2200,
                        "fill_volume": 2000,
                        "fill_concentration": 2.5,
                        "uf": 200
                    }
                ]
            }
        }
    )
    record_date: Optional[date] = Field(None, description="기록 날짜, 비워두면 오늘 날짜 사용")
    record_dw: DayWeekKR = Field(..., description="요일: 월/화/수/목/금/토/일")
    weight: float = Field(..., ge=30.0, le=200.0)
    systolic: int = Field(..., ge=70, le=240)
    diastolic: int = Field(..., ge=40, le=160)
    fasting_glucose: int = Field(..., ge=40, le=600)
    urine_count: int = Field(..., ge=0, le=30)
    turbidity: Turbidity = Field(..., description="'없음' 또는 '있음'")
    notes: Optional[str] = None
    total_uf: int = Field(..., ge=-2500, le=2500, description="제수량 합계")
    gcs_path: Optional[str] = None
    exchanges: List[RecordExchangeCreate] = Field(..., min_length=1, max_length=5, description="회차별 정보 (1~5개)")


# 회차 정보 수정 스키마
class RecordExchangePatch(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 123,
                "exchange_time": "10:30",
                "drain_volume": 2200
            }
        }
    )
    id: int = Field(..., description="수정할 회차의 ID")
    exchange_no: Optional[int] = Field(None, ge=1, le=5, description="구분(회차)")
    exchange_time: Optional[TimeStr] = Field(None, description="HH:MM 또는 HH:MM:SS")
    drain_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_concentration: Optional[float] = Field(None, ge=0, le=100)
    uf: Optional[int] = Field(None, ge=-500, le=500)


# 공통 + 회차 정보 동시 수정 스키마
class RecordPatch(RecordCommonPatch):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "record_date": "2025-11-24",
                "weight": 56.2,
                "turbidity": "있음",
                "notes": "복막액이 약간 혼탁하지만 통증은 없음",
                "total_uf": 550,
                "exchanges": [
                    {
                        "id": 101,
                        "exchange_time": "08:30",
                        "drain_volume": 2150,
                        "fill_volume": 2000,
                        "fill_concentration": 1.5,
                        "uf": 150
                    },
                    {
                        "id": 102,
                        "drain_volume": 2250,
                        "uf": 250
                    }
                ]
            }
        }
    )
    exchanges: Optional[List[RecordExchangePatch]] = Field(
        default=None,
        description="수정할 회차 기록 리스트 (각 항목은 id 필수, 나머지는 부분 수정 가능)"
    )


class TodayExchangeSummary(BaseModel):
    has_record: bool = Field(..., description="오늘 날짜에 복막투석 기록이 존재하는지의 여부", examples=[True])
    exchange_count: int = Field(..., ge=0, le=5, description="오늘 완료된 교환 회차 개수", examples=[4])
    total_uf: int = Field(..., ge=-2500, le=2500, description="오늘의 제수량 합계 (단위: g)", examples=[500])