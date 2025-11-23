from datetime import datetime
from enum import Enum

from app.models.record_schemas import ORMBase

class MessageRole(str, Enum):
    USER = "USER"
    AGENT = "AGENT"

# 환영 메시지
class SessionStartResponse(ORMBase):
    session_id: str
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


class ConsultSessionSummary(ORMBase):
    session_id: str
    started_at: datetime        # 해당 세션의 첫 메시지 시각
    message_count: int          # 총 메시지 개수

class ConsultMessage(ORMBase):
    role: MessageRole
    content: str
    created_at: datetime
