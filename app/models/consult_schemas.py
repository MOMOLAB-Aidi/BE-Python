from uuid import UUID

from pydantic import BaseModel

from app.models.record_schemas import ORMBase


# 환영 메시지
class SessionStartResponse(ORMBase):
    session_id: UUID
    message: str


# 사용자 질문
class ChatRequest(ORMBase):
    session_id: str
    message: str

# 에이전트 응답
class ChatResponse(ORMBase):
    session_id: str
    response: str

class SessionEndRequest(ORMBase):
    session_id: str

class SessionEndResponse(ORMBase):
    session_id: str
    status: str