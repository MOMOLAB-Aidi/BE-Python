from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.db import Base


class ConsultSummary(Base):
    __tablename__ = "consult_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    user = relationship("User", back_populates="consult_summary_list")

    session_id = Column(String(64), nullable=False, index=True)

    summary = Column(String(512), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_consult_summary_user_session"),
    )