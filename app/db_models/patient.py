from sqlalchemy import Column, Integer, String
from app.core.db import Base
from app.db_models.base_entity import TimestampMixin


# 환자 테이블 정의
class Patient(Base, TimestampMixin):
    __tablename__ = "patient"
    id = Column(Integer, primary_key=True, index=True)
    loginId = Column(String(50), nullable=False) # 환자 아이디 (로그인용)
    password = Column(String(100), nullable=False) # 환자 비밀번호 (로그인용)
