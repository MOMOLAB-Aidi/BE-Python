from datetime import datetime
from typing import Optional, Literal, List, Annotated
from pydantic import BaseModel, Field, ConfigDict

today = datetime.now()
today_str = today.strftime("%Y-%m-%d")
time_str = today.strftime("%H:%M")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# 회차(개별) 스키마
class RecordExchangeCreate(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exchange_no": 1,
                "exchange_time": time_str,
                "drain_volume": 2100,
                "fill_volume": 2000,
                "fill_concentration": 2.5
            }
        }
    )
    exchange_no: int = Field(..., ge=1, le=12, description="구분(회차)")
    exchange_time: str = Field(..., description="HH:MM")
    drain_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_concentration: Optional[float] = Field(None, ge=0, le=100, description="예: 1.5, 2.5, 4.25")


class RecordExchangePatch(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exchange_time": time_str,
                "drain_volume": 2200
            }
        }
    )
    exchange_no: Optional[int] = Field(None, ge=1, le=12)
    exchange_time: Optional[str] = None
    drain_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_volume: Optional[int] = Field(None, ge=0, le=6000)
    fill_concentration: Optional[float] = Field(None, max_length=16)


class RecordExchangeRead(ORMBase):
    id: int
    exchange_no: int
    exchange_time: str
    drain_volume: Optional[int] = None
    fill_volume: Optional[int] = None
    fill_concentration: Optional[float] = None
    uf: int = Field(..., description="제수량(배액량g - 주입액중량g) *계산필드*")


# 일일(공통) 스키마
Turbidity = Literal["없음", "있음"]

class RecordCreate(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "record_date": today_str,
                "weight": 61.5,
                "systolic": 118,
                "diastolic": 72,
                "fasting_glucose": 95,
                "urine_count": 6,
                "turbidity": "없음",
                "notes": "환자의 상태 양호",
                "exchanges": [
                    {
                        "exchange_no": 1,
                        "exchange_time": "07:30",
                        "drain_volume": 2100,
                        "fill_volume": 2000,
                        "fill_concentration": 2.5
                    },
                    {
                        "exchange_no": 2,
                        "exchange_time": "12:00",
                        "drain_volume": 2050,
                        "fill_volume": 2000,
                        "fill_concentration": 2.5
                    }
                ]
            }
        }
    )
    record_date: str = Field(..., description="YYYY-MM-DD")
    weight: float = Field(..., ge=20.0, le=300.0)
    systolic: int = Field(..., ge=70, le=240)
    diastolic: int = Field(..., ge=40, le=160)
    fasting_glucose: Optional[int] = Field(None, ge=40, le=600)
    urine_count: Optional[int] = Field(None, ge=0, le=50)
    turbidity: Optional[Turbidity] = None
    notes: Optional[str] = Field(None, max_length=2000)
    # 회차들 함께 생성 가능
    exchanges: Annotated[list[RecordExchangeCreate], Field(default_factory=list)]


class RecordPatch(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "weight": 61.2,
                "turbidity": "있음",
                "notes": "복막액 약간 혼탁, 통증 없음"
            }
        }
    )
    record_date: Optional[str] = None
    weight: Optional[float] = Field(None, ge=20.0, le=300.0)
    systolic: Optional[int] = Field(None, ge=70, le=240)
    diastolic: Optional[int] = Field(None, ge=40, le=160)
    fasting_glucose: Optional[int] = Field(None, ge=40, le=600)
    urine_count: Optional[int] = Field(None, ge=0, le=50)
    turbidity: Optional[Turbidity] = None
    notes: Optional[str] = Field(None, max_length=2000)


class RecordRead(ORMBase):
    id: int
    record_date: str
    weight: float
    systolic: int
    diastolic: int
    fasting_glucose: Optional[int] = None
    urine_count: Optional[int] = None
    turbidity: Optional[Turbidity] = None
    notes: Optional[str] = None
    total_uf: int = Field(..., description="Σ(배액량ml - 주입액중량g) *계산필드*")
    exchanges: List[RecordExchangeRead]


# 에이전트 입력 (자연어 지시)
class AgentIn(ORMBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"text": "혈압 125/78만 기록"}
        }
    )
    text: str = Field(..., description="자연어 명령/요청")