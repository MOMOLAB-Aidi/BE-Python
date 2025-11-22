from typing import Iterable

from google import genai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from app.db_models.kdigo_chunk import KdigoChunk

client = genai.Client()


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
def embed_texts_with_gemini(texts: Iterable[str]) -> list[list[float]]:

    text_list = list(texts)
    if not text_list:
        return []

    # 한 번에 배치로 임베딩
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text_list,
    )

    # response.embeddings -> 각 embedding 객체, 실제 벡터는 .values 에 들어 있음
    embeddings: list[list[float]] = [e.values for e in response.embeddings]
    return embeddings


def build_kdigo_chunks(
    db: Session,
    kdigo_text: str,
    clear_existing: bool = True,
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

    # 0. 기존 데이터 삭제 옵션
    if clear_existing:
        db.query(KdigoChunk).delete()
        db.commit()

    # 1. chunking
    chunks = chunk_kdigo_text(kdigo_text, chunk_size, chunk_overlap)
    if not chunks:
        print("[KDIGO Preprocess] 청크가 생성되지 않았습니다.")
        return 0

    print(f"[KDIGO Preprocess] 생성된 청크 수: {len(chunks)}")

    # 2. 임베딩
    embeddings = embed_texts_with_gemini(chunks)
    if len(embeddings) != len(chunks):
        raise RuntimeError("청크 개수와 임베딩 개수가 일치하지 않습니다.")

    # 3. DB 저장
    for content, emb in zip(chunks, embeddings):
        row = KdigoChunk(
            content=content,
            embedding=emb,
        )
        db.add(row)

    db.commit()
    print(f"[KDIGO Preprocess] {len(chunks)}개 청크를 DB에 저장했습니다.")
    return len(chunks)
