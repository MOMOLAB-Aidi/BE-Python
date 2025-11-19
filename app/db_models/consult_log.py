from sqlalchemy import Column, Integer, ForeignKey, String, Enum, Text
from sqlalchemy.orm import relationship

from app.core.db import Base

ConsultRoleEnum = Enum("USER", "AGENT", name="consult_role_enum")

class ConsultLog(Base):
    __tablename__ = "consult_log"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="consult_log_list")

    session_id = Column(String, nullable=False) # 해당 메시지가 속한 상담 세션 ID
    role = Column(ConsultRoleEnum, nullable=False) # 메시지의 주체
    content = Column(Text, nullable=False) # 대화 내용
