import os
from collections.abc import Generator

import sqlalchemy
from google.cloud.sql.connector import Connector
from sqlalchemy import Column, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

USE_CLOUD_SQL = os.getenv("USE_CLOUD_SQL", "0") == "1"

def get_engine():
    if USE_CLOUD_SQL:
        # Cloud Run/로컬에서 Cloud SQL을 정말 쓸 때만 로드
        connector = Connector()

        def getconn():
            return connector.connect(
                os.environ["INSTANCE_CONNECTION_NAME"],
                "pg8000",
                user=os.environ["DB_USER"],
                password=os.environ["DB_PASSWORD"],
                db=os.environ["DB_NAME"],
            )
        return sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn, pool_pre_ping=True)
    else:
        # 로컬/테스트는 SQLite 등으로
        db_url = os.getenv("DATABASE_URL", "sqlite:///./test.db")
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