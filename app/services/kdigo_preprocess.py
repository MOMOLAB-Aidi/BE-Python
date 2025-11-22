import logging
import os
from typing import Iterable

from google import genai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from app.db_models.kdigo_chunk import KdigoChunk

logger = logging.getLogger(__name__)

try:
    # API 키가 설정되어 있는지 확인
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        client = genai.Client()
    else:
        client = None
        logger.warning("[KDIGO Preprocess] 경고: Gemini API 키가 설정되지 않았습니다.")
except Exception as e:
    client = None
    logger.error(f"[KDIGO Preprocess] Gemini 클라이언트 초기화 실패: {e}")


# KDIGO 원문 텍스트를 LangChain으로 chunking
def chunk_kdigo_text(
    raw_text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 200,
) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],  # 문단/줄/공백 우선 분할
    )
    chunks = splitter.split_text(raw_text)
    # 너무 짧은 chunk는 걸러도 됨 (선택)
    chunks = [c.strip() for c in chunks if c.strip()]
    return chunks


# gemini embedding-001 모델로 여러 텍스트를 임베딩
# 배치 크기 제한
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
def embed_texts_with_gemini(texts: Iterable[str]) -> list[list[float]]:
    if client is None:
        raise RuntimeError("Gemini 클라이언트가 초기화되지 않았습니다. API 키를 확인하세요.")

    text_list = list(texts)
    if not text_list:
        return []

    try:
        # 한 번에 배치로 임베딩
        response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text_list,
        )
    except Exception as e:
        logger.error(f"[KDIGO Preprocess] 임베딩 API 호출 실패: {e}", exc_info=True)
        raise

    # response.embeddings -> 각 embedding 객체, 실제 벡터는 .values 에 들어 있음
    embeddings: list[list[float]] = [e.values for e in response.embeddings]
    return embeddings


def build_kdigo_chunks(
    db: Session,
    kdigo_text: str,
    clear_existing: bool = False,
    chunk_size: int = 800,
    chunk_overlap: int = 200,
) -> int:
    """
    KDIGO 원문 텍스트를 받아서:
    - chunking (LangChain)
    - Gemini로 임베딩
    - Postgres(kdigo_chunks)에 저장

    return: 생성된 청크 개수
    """

    try:
        # 0. 기존 데이터 삭제 옵션
        if clear_existing:
            # 안전을 위해 삭제 전 개수 확인
            count = db.query(KdigoChunk).count()
            if count > 0:
                logger.warning(f"[KDIGO Preprocess] 경고: {count}개의 기존 청크를 삭제합니다.")
            db.query(KdigoChunk).delete()
            db.commit()

        # 1. chunking
        chunks = chunk_kdigo_text(kdigo_text, chunk_size, chunk_overlap)
        if not chunks:
            logger.warning("청크가 생성되지 않았습니다.")
            return 0

        logger.info(f"생성된 청크 수: {len(chunks)}")

        # 2. 임베딩
        embeddings = embed_texts_with_gemini(chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError("청크 개수와 임베딩 개수가 일치하지 않습니다.")

        # 3. DB 저장
        for content, emb in zip(chunks, embeddings, strict=True):
            row = KdigoChunk(
                content=content,
                embedding=emb,
            )
            db.add(row)

        db.commit()
        logger.info(f"{len(chunks)}개 청크를 DB에 저장했습니다.")
        return len(chunks)
    except Exception as e:
        db.rollback()
        logger.error(f"[KDIGO Preprocess] 에러 발생: {e}")
        raise
