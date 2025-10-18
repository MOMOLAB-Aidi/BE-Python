from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict

today = datetime.now()
today_str = today.strftime("%Y-%m-%d")
time_str = today.strftime("%H:%M")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RecordCreate(ORMBase):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "record_date": today_str,
                "record_time": time_str,
                "exchange_count": 3,
                "systolic": 118,
                "diastolic": 72,
                "weight_kg": 61.5,
                "outflow_ml": 2100,
                "clarity": "맑음",
                "abdominal_pain": "없음",
                "exit_site": "정상",
            }
        },
    )
    record_date: str = Field(..., description="YYYY-MM-DD")
    record_time: str = Field(..., description="HH:MM")
    exchange_count: int = Field(..., ge=1, le=10)
    systolic: int = Field(..., ge=70, le=240)
    diastolic: int = Field(..., ge=40, le=160)
    weight_kg: float = Field(..., ge=20.0, le=300.0)
    outflow_ml: int = Field(..., ge=0, le=5000)
    clarity: Literal["맑음", "탁함"]
    abdominal_pain: Literal["없음", "이상"]
    exit_site: Literal["정상", "이상"]


class RecordPatch(ORMBase):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "record_date": today_str,
                "record_time": time_str,
                "exchange_count": 3,
                "systolic": 118,
                "diastolic": 72,
                "weight_kg": 61.5,
                "outflow_ml": 2100,
                "clarity": "맑음",
                "abdominal_pain": "없음",
                "exit_site": "정상",
            }
        },
    )
    record_date: Optional[str] = None
    record_time: Optional[str] = None
    exchange_count: Optional[int] = None
    systolic: Optional[int] = None
    diastolic: Optional[int] = None
    weight_kg: Optional[float] = None
    outflow_ml: Optional[int] = None
    clarity: Optional[Literal["맑음", "탁함"]] = None
    abdominal_pain: Optional[Literal["없음", "이상"]] = None
    exit_site: Optional[Literal["정상", "이상"]] = None


class AgentIn(ORMBase):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "text": "혈압 125/78만 기록"
            }
        },
    )
    text: str
