from sqlalchemy import Column, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base

class kdigo_chunk(Base):
    __tablename__ = 'kdigo_chunks'

    id = Column(Integer, primary_key=True, index=True)

    content = Column(Text) # 가이드라인 텍스트 청크
    embedding = Column(JSONB) # [float, float, ...] 리스트 그대로 저장