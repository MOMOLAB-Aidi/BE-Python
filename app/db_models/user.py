from sqlalchemy import Column, Integer, String
from app.core.db import Base
from app.db_models.base_entity import TimestampMixin


# 사용자 테이블 정의
class User(Base, TimestampMixin):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)