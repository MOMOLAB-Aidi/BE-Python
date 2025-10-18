from sqlalchemy import Column, Integer, Date, Time, Float, String
from app.core.db import Base
from app.db_models.base_entity import TimestampMixin


# 복막투석기록 테이블 정의
class Record(Base, TimestampMixin):
    __tablename__ = "record"
    id = Column(Integer, primary_key=True, index=True)
    record_date = Column(Date, nullable=False)
    record_time = Column(Time, nullable=False)
    exchange_count = Column(Integer, nullable=False) # 교환회차
    systolic = Column(Integer, nullable=False) # 최고혈압
    diastolic = Column(Integer, nullable=False) # 최저혈압
    weight_kg = Column(Float, nullable=False) # 체중
    outflow_ml = Column(Integer, nullable=False) # 유출량
    clarity = Column(String(10), nullable=False) # 혼탁도: '맑음'|'탁함'
    abdominal_pain = Column(String(10), nullable=False) # 복통: '없음'|'이상'
    exit_site = Column(String(10), nullable=False) # 주사구: '정상'|'이상'