from collections.abc import Generator

from sqlalchemy import create_engine, Column, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

# 죽은 커넥션 자동 감지
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# BaseEntity에 해당하는 공통 필드 믹스인
class BaseEntity:
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

# 모든 모델이 상속할 Base
Base = declarative_base(cls=BaseEntity)

# DB 세션
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()