from sqlalchemy import Column, Integer, Date, Float, Enum, Text
from sqlalchemy.orm import relationship

from app.core.db import Base
from app.db_models.base_entity import TimestampMixin

# 복막투석기록일지 - 공통 데이터 정의
TurbidityEnum = Enum("없음", "있음", name="turbidity_enum")
DayWeekEnum = Enum("월", "화", "수", "목", "금", "토", "일", name="dayweek_enum")

class Record(Base, TimestampMixin):
    __tablename__ = "record"

    id = Column(Integer, primary_key=True, index=True)
    record_date = Column(Date, nullable=False) # 기록 날짜
    record_dw = Column(DayWeekEnum, nullable=False) # 기록 요일

    weight = Column(Float, nullable=False)  # 체중 (kg)

    systolic = Column(Integer, nullable=False) # 최고 혈압
    diastolic = Column(Integer, nullable=False) # 최저 혈압

    fasting_glucose = Column(Integer, nullable=False) # 공복 혈당 (mg/dL)
    urine_count = Column(Integer, nullable=False) # 소변 횟수 (회)
    turbidity = Column(TurbidityEnum, nullable=False)  # 복막액 혼탁(없음/있음)
    notes = Column(Text, nullable=True) # 비고

    total_uf = Column(Integer, nullable=True)  # 제수량 합계

    # 관계: 회차별 데이터
    exchanges = relationship(
        "RecordExchange",
        back_populates="record",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecordExchange.exchange_no",
    )