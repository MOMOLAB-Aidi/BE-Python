from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.orm import relationship

from app.core.db import Base

UserStatusEnum = Enum("ACTIVE", "INACTIVE", name="user_status_enum")
UserRoleEnum = Enum("USER", "ADMIN", name="user_role_enum")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    login_id = Column(String, unique=True, nullable=False) # 아이디(고유번호)
    password = Column(String, nullable=False) # 비밀번호
    last_login_at = Column(DateTime, nullable=True) # 마지막에 로그인한 시각
    status = Column(UserStatusEnum, nullable=False) # 활성화 여부
    role = Column(UserRoleEnum, nullable=False) # 권한

    record_list = relationship(
        "Record",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    record_exchange_list = relationship(
        "RecordExchange",
        back_populates="user",
        cascade="all, delete-orphan"
    )