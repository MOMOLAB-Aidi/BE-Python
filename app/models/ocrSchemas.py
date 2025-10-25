from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class OcrResponse(ORMBase):
    filename: str
    content_type: str
    size_bytes: int
    model: str
    text: str