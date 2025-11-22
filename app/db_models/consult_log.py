from sqlalchemy import Column, Integer, ForeignKey, String, Enum, Text
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum

from app.core.db import Base

class ConsultRoleEnum(str, PyEnum):
    USER = "USER"
    AGENT = "AGENT"

class ConsultLog(Base):
    __tablename__ = "consult_log"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="consult_log_list")

    session_id = Column(String, nullable=False, index=True) # 해당 메시지가 속한 상담 세션 ID

    role = Column(
        Enum(ConsultRoleEnum, name="consult_role_enum"),
        nullable=False,
    )

    content = Column(Text, nullable=False) # 대화 내용
