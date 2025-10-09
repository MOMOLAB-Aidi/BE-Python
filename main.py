from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from app.core.db import engine, Base
from app.api.routes import router as api_router

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
    # 앱 시작 시 테이블 생성 (Alembic 안 쓸 때 편리)
    Base.metadata.create_all(bind=engine)
    yield
    # 앱 종료 시 리소스 정리 필요하면 여기서 처리 (예: engine.dispose())

app = FastAPI(
    title="RAG Chatbot API",
    description="RAG 챗봇 API",
    version="0.1.0",
    middleware=middleware,
    lifespan=lifespan,
)

# 라우터 등록
app.include_router(api_router)

# 헬스/루트
@app.get("/", tags=["health"])
def read_root():
    return {"message": "RAG Chatbot API", "status": "ok"}

# 로컬 실행 진입점 (uvicorn CLI로 실행해도 무방)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)