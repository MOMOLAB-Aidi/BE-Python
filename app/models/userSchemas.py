from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreateResult(ORMBase):
    id: int
    name: str
    email: str


class UserGetResult(ORMBase):
    id: int
    name: str
    email: str


class UserUpdateResult(ORMBase):
    id: int
    name: str
    email: str


class UserDeleteResult(ORMBase):
    id: int
    name: str
    email: str
