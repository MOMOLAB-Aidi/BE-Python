from typing import List, Dict, Any, Optional

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class OcrSaveRequest(ORMBase):
    record: Dict[str, Any]
    gcs_path: str

class RecordFinalizeBody(ORMBase):
    record_date: str
    record_dw: str
    exchanges: List[Dict[str, Any]]
    weight: float
    blood_pressure: Dict[str, Optional[int]]
    fasting_glucose: int
    urine_count: int
    turbidity: str
    total_uf: Optional[int] = None
    notes: Optional[str] = None