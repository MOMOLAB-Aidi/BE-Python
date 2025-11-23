from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, Text

from app.core.db import Base

# gemini embedding-001이 반환하는 차원 수 (현재 3072)
KDIGO_EMBED_DIM = 3072

class KdigoChunk(Base):
    __tablename__ = 'kdigo_chunks'

    id = Column(Integer, primary_key=True, index=True)

    content = Column(Text, nullable=False) # KDIGO 텍스트 청크
    embedding = Column(Vector(KDIGO_EMBED_DIM), nullable=False) # 임베딩 벡터