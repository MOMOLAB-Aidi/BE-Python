from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from app.core.db import engine, Base
from app.api.routes import router as api_router

import uvicorn

ALLOWED_ORIGINS = [
    "http://127.0.0.1:8000",
]

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
    Base.metadata.create_all(bind=engine)

    try:
        yield
    finally:
        # 커넥션 풀 정리
        engine.dispose()


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
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
