import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import Base, get_engine, shutdown_db, init_pgvector_extension
from app.api.routes import router as api_router

import uvicorn

ALLOWED_ORIGINS = settings.ALLOWED_ORIGINS

# CORS
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]


@asynccontextmanager
async def lifespan(app: FastAPI):

    # 앱 시작 시 테이블 생성
    engine = get_engine()

    init_pgvector_extension()
    Base.metadata.create_all(bind=engine)

    try:
        yield
    finally:
        # 커넥션 풀 + Cloud SQL Connector 백그라운드 스레드 정리
        shutdown_db()


app = FastAPI(
    title="MOMOLAB AIDI API",
    description="MOMOLAB 에이디 API",
    version="0.1.0",
    middleware=middleware,
    lifespan=lifespan,
)

# 라우터 등록
app.include_router(api_router)


# 헬스/루트
@app.get("/", tags=["health"])
def read_root():
    return {"message": "MOMOLAB AIDI API", "status": "ok"}


# 로컬 실행 진입점
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
