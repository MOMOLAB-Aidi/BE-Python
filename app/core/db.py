import atexit
import threading
from collections.abc import Generator
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Tuple, TYPE_CHECKING

import sqlalchemy
from fastapi import FastAPI
from sqlalchemy import Column, DateTime, func, Engine, URL
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

if TYPE_CHECKING:
    from google.cloud.sql.connector import Connector

# 전역 상태
_db_lock = threading.Lock()
_connector: Optional["Connector"] = None
_engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker] = None

# BaseEntity에 해당하는 공통 필드 믹스인
class BaseEntity:
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

# 모든 모델이 상속할 Base
Base = declarative_base(cls=BaseEntity)

def _create_engine_and_connector() -> Tuple[Engine, Optional["Connector"]]:
    """
    Engine과 필요 시 Connector를 생성해 반환.
    호출 측에서 전역 보관 후 종료 시 정리
    """
    if settings.USE_CLOUD_SQL:
        try:
            from google.cloud.sql.connector import Connector
        except ModuleNotFoundError as exc:
            raise CloudSQLConfigError(
                "Cloud SQL을 사용하려면 google-cloud-sql-connector가 설치되어야 합니다."
            ) from exc

        # 필수 환경 변수 검증
        if not all([settings.INSTANCE_CONNECTION_NAME, settings.DB_USER, settings.DB_PASSWORD, settings.DB_NAME]):
            raise CloudSQLConfigError()

        connector = Connector()

        def getconn():
            return connector.connect(
                settings.INSTANCE_CONNECTION_NAME,
                "pg8000",
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                db=settings.DB_NAME,
            )

        engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
            pool_pre_ping=True,
        )
        return engine, connector

    # 개별 값 기반 DSN
    if not (settings.DB_USER and settings.DB_PASSWORD and settings.DB_NAME):
        raise RuntimeError(
            "DB 연결 정보 부족: (Cloud SQL) USE_CLOUD_SQL=true 또는 DB_USER/DB_PASSWORD/DB_NAME을 설정하세요."
        )

    host = getattr(settings, "DB_HOST", None) or "localhost"
    port = int(getattr(settings, "DB_PORT", 5432) or 5432)
    driver = getattr(settings, "DB_DRIVER", "psycopg")  # psycopg 또는 pg8000

    url = URL.create(
        drivername = f"postgresql+{driver}",
        username = settings.DB_USER,
        password = settings.DB_PASSWORD,
        host = host,
        port = port,
        database = settings.DB_NAME,
    )
    engine = sqlalchemy.create_engine(url, pool_pre_ping=True)
    return engine, None

# 최초 접근 시 1회만 초기화
def init_db_if_needed() -> None:
    global _engine, _connector, SessionLocal
    if _engine is not None:
        return
    with _db_lock:
        if _engine is None:
            _engine, _connector = _create_engine_and_connector()
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


# 애플리케이션 종료 시 자원 정리
def shutdown_db() -> None:
    global _engine, _connector, SessionLocal
    with _db_lock:
        try:
            if _engine is not None:
                _engine.dispose() # 풀 커넥션 정리
        finally:
            _engine = None
            SessionLocal = None
        if _connector is not None:
            try:
                _connector.close()
            finally:
                _connector = None


# 프로세스 종료 시 비상 정리
atexit.register(shutdown_db)


# 외부에서 엔진이 필요할 때 호출
def get_engine() -> Engine:
    init_db_if_needed()
    if _engine is None:
        raise RuntimeError("데이터베이스 엔진 초기화 실패")
    return _engine


# 요청 단위 세션
def get_db() -> Generator[Session, None, None]:
    init_db_if_needed()
    if SessionLocal is None:
        raise RuntimeError("SessionLocal 초기화 실패")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 배치/스크립트용 컨텍스트 매니저
@contextmanager
def db_session() -> Generator[Session, None, None]:
    init_db_if_needed()
    if SessionLocal is None:
        raise RuntimeError("SessionLocal 초기화 실패")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# FastAPI와 생명주기 연동
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: yield 이전에 실행
    init_db_if_needed()
    yield
    # Shutdown: yield 이후에 실행
    shutdown_db()

# Cloud SQL 설정 오류
class CloudSQLConfigError(Exception):
    def __init__(self, message: Optional[str] = None):
        if message is None:
            message = (
                "Cloud SQL 사용 시 INSTANCE_CONNECTION_NAME, DB_USER, "
                "DB_PASSWORD, DB_NAME이 모두 필요합니다."
            )
        super().__init__(message)