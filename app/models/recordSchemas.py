from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class RecordCreate(ORMBase):
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
    text: str
