import os
from collections.abc import Generator

import sqlalchemy
from google.cloud.sql.connector import Connector
from sqlalchemy import Column, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

USE_CLOUD_SQL = os.getenv("USE_CLOUD_SQL", "0") == "1"

def get_engine():
    if USE_CLOUD_SQL:
        # Cloud SQL 필수 환경 변수 검증
        instance_name = os.getenv("INSTANCE_CONNECTION_NAME")
        if not all([instance_name, settings.DB_USER, settings.DB_PASSWORD, settings.DB_NAME]):
            raise ValueError("Cloud SQL 사용 시 INSTANCE_CONNECTION_NAME, DB_USER, DB_PASSWORD, DB_NAME이 모두 필요합니다.")
        # Cloud Run/로컬에서 Cloud SQL을 쓸 때만 로드
        connector = Connector()

        def getconn():
            return connector.connect(
                instance_name,
                "pg8000",
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                db = settings.DB_NAME,
            )
        return sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn, pool_pre_ping=True)
    else:
        # 로컬/테스트는 SQLite 등으로
        db_url = settings.DATABASE_URL or "sqlite:///./test.db"
        return sqlalchemy.create_engine(db_url, pool_pre_ping=True)

engine = get_engine()

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