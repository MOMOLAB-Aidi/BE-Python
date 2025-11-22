from sqlalchemy import Column, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base

class KdigoChunk(Base):
    __tablename__ = 'kdigo_chunks'

    id = Column(Integer, primary_key=True, index=True)

    content = Column(Text, nullable=False) # KDIGO 텍스트 청크
    embedding = Column(JSONB, nullable=False) # [float, float, ...] 리스트 그대로 저장