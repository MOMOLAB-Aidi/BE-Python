from typing import List

from fastapi import Depends, HTTPException, APIRouter
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.db_models.user import User
from pydantic import BaseModel

from app.models.userSchemas import UserCreateResult, UserGetResult, UserUpdateResult, UserDeleteResult

router = APIRouter()


# 사용자 등록 요청 모델
class UserCreate(BaseModel):
    name: str
    email: str


# 사용자 등록 api
@router.post("/api/users",
             tags=["사용자"],
             response_model=UserCreateResult,
             summary="사용자 등록",
             description="사용자를 등록하는 api입니다.",
             responses={
                 200: {
                     "description": "사용자 등록 예시 응답",
                     "content": {
                         "application/json": {
                             "example": {
                                 "id": 1,
                                 "name": "momo",
                                 "email": "momolab@gmail.com",
                             }
                         }
                     }
                 }
             })
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = User(name=user.name, email=user.email)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


# 사용자 목록 조회 api
@router.get("/api/users",
            tags=["사용자"],
            response_model=List[UserGetResult],
            summary="사용자 목록 조회",
            description="사용자 목록을 조회하는 api입니다.",
            responses={
                200: {
                    "description": "사용자 목록 조회 예시 응답",
                    "content": {
                        "application/json": {
                            "example": {
                                "id": 1,
                                "name": "momo",
                                "email": "momolab@gmail.com",
                            }
                        }
                    }
                }
            })
def read_users(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    users = db.query(User).offset(skip).limit(limit).all()
    return users


# 사용자 정보 업데이트 요청 모델
class UserUpdate(BaseModel):
    name: str
    email: str


# 사용자 정보 업데이트 api
@router.put("/api/users/{user_id}",
            tags=["사용자"],
            response_model=UserUpdateResult,
            summary="사용자 정보 업데이트",
            description="사용자의 정보를 업데이트하는 api입니다.",
            responses={
                200: {
                    "description": "사용자 정보 업데이트 예시 응답",
                    "content": {
                        "application/json": {
                            "example": {
                                "id": 1,
                                "name": "momo",
                                "email": "momolab@gmail.com",
                            }
                        }
                    }
                }
            })
def update_user(user_id: int, user: UserUpdate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.name = user.name
    db_user.email = user.email
    db.commit()
    db.refresh(db_user)
    return db_user


# 사용자 삭제 api
@router.delete("/api/users/{user_id}",
               tags=["사용자"],
               response_model=UserDeleteResult,
               summary="사용자 삭제",
               description="사용자를 삭제하는 api입니다.",
               responses={
                   200: {
                       "description": "사용자 삭제 예시 응답",
                       "content": {
                           "application/json": {
                               "example": {
                                   "id": 1,
                                   "name": "momo",
                                   "email": "momolab@gmail.com",
                               }
                           }
                       }
                   }
               })
def delete_user(user_id: int, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    return {"message": "User deleted successfully"}
