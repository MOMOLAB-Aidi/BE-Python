from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.orm import relationship

from app.core.db import Base

UserStatusEnum = Enum("ACTIVE", "INACTIVE", name="user_status_enum")
UserRoleEnum = Enum("USER", "ADMIN", name="user_role_enum")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    loginId = Column(String, unique=True, nullable=False) # 아이디(고유번호)
    password = Column(String, nullable=False) # 비밀번호
    lastLoginAt = Column(DateTime, nullable=True) # 마지막에 로그인한 시각
    status = Column(UserStatusEnum, nullable=False) # 활성화 여부
    role = Column(UserRoleEnum, nullable=False) # 권한

    refresh_token = relationship(
        "RefreshToken",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    record_list = relationship(
        "Record",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )