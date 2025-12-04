from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

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


class ConsultSession(ORMBase):
    session_id: str
    ended_at: datetime = Field(..., description="해당 세션의 종료 날짜와 시각")
    first_user_question: Optional[str] = Field(None, description="환자의 첫 질문")
    summary: Optional[str] = Field(None, description="전보(telegram) 스타일 상담 요약")

class ConsultMessage(ORMBase):
    role: MessageRole
    content: str
    created_at: datetime

class ConsultSessionSummaryRow(ORMBase):
    session_id: str
    summary: str = Field(..., description="전보(telegram) 스타일 상담 요약")