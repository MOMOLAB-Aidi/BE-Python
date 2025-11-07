from sqlalchemy import Column, Integer, ForeignKey, Time, Index, Float
from sqlalchemy.orm import relationship

from app.core.db import Base


# 복막투석기록일지 - 회차별 데이터 정의 (같은 날짜의 여러 교환 회차)
class RecordExchange(Base):
    __tablename__ = "record_exchange"

    id = Column(Integer, primary_key=True)
    record_id = Column(
        Integer, ForeignKey("record.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    exchange_no = Column(Integer, nullable=False) # 구분(회차)
    exchange_time = Column(Time, nullable=False) # 교환 시각

    drain_volume = Column(Integer, nullable=False) # 배액량 (g)
    fill_volume = Column(Integer, nullable=False)  # 주입량 (g)
    fill_concentration = Column(Float, nullable=False) # 주입액 농도 (%)

    uf = Column(Integer, nullable=False) # 제수량 (배액량 - 주입액 중량)

    record = relationship("Record", back_populates="exchanges")


# 조회/정합성 인덱스
Index("ix_record_exchange_record_no",
      RecordExchange.record_id, RecordExchange.exchange_no)