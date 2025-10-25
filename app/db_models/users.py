from sqlalchemy import Column, Integer, String, Date, Enum
from app.core.db import Base
from app.db_models.base_entity import TimestampMixin


# 사용자 테이블 정의

GenderEnum = Enum("MALE", "FEMALE", name="gender_enum")
UserStatus = Enum("ACTIVE", "INACTIVE", name="status_enum")
RoleEnum = Enum("USER", "ADMIN", name="role_enum")

class Users(Base, TimestampMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(20), nullable=False) # 이름
    phoneNum = Column(String(11), nullable=False) # 휴대폰번호
    birth = Column(Date, nullable=False) # 생년월일
    gender = Column(GenderEnum, nullable = False) # 성별
    status = Column(UserStatus, nullable=False) # 활성화 여부
    role = Column(RoleEnum, nullable=False) # 권한
