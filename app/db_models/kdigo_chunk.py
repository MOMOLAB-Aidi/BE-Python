from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, Text, Index

from app.core.db import Base

# KDIGO 임베딩 설정
KDIGO_EMBED_DIM = 768

class KdigoChunk(Base):
    __tablename__ = 'kdigo_chunks'

    id = Column(Integer, primary_key=True, index=True)

    content = Column(Text, nullable=False) # KDIGO 텍스트 청크
    embedding = Column(Vector(KDIGO_EMBED_DIM), nullable=False) # 임베딩 벡터

    __table_args__ = (
        Index(
            "ix_kdigo_chunks_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},  # 클러스터 수
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )