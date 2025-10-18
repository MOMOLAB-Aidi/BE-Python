from typing import List

from fastapi import Depends, HTTPException, APIRouter
from sqlalchemy.orm import Session
from datetime import date as _date

from app.core.db import get_db

from app.db_models.user import User
from app.db_models.record import Record

from pydantic import BaseModel

from app.models.userSchemas import UserCreateResult, UserGetResult, UserUpdateResult, UserDeleteResult
from app.models.recordSchemas import RecordCreate, RecordPatch, AgentIn
from app.services.recordService import parse_time, rec_to_dict, apply_patch, agent_text_to_patch

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


# 복막투석기록 생성 api
@router.post("/api/records",
             tags=["복막투석기록"],
             summary="기록 생성",
             description="복막투석기록을 생성하는 api입니다.",
             )
def create_record(record: RecordCreate, db: Session = Depends(get_db)):
    try:
        d = _date.fromisoformat(record.record_date) if record.record_date else _date.today()
        t = parse_time(record.record_time)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    rec = Record(
        record_date=d, record_time=t,
        exchange_count=record.exchange_count,
        systolic=record.systolic, diastolic=record.diastolic,
        weight_kg=record.weight_kg, outflow_ml=record.outflow_ml,
        clarity=record.clarity, abdominal_pain=record.abdominal_pain, exit_site=record.exit_site,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec_to_dict(rec)


# 특정 복막투석기록 조회 api
@router.get("/api/records/{rec_id}",
             tags=["복막투석기록"],
             summary="기록 조회",
             description="특정 복막투석기록을 조회하는 api입니다.",)
def get_record(rec_id: int, db: Session = Depends(get_db)):
    rec = db.query(Record).get(rec_id)
    if not rec: raise HTTPException(status_code=404, detail="not found")
    return rec_to_dict(rec)


# 복막투석기록 수정 api
@router.patch("/api/records/{rec_id}",
             tags=["복막투석기록"],
             summary="기록 수정",
             description="복막투석기록을 수정하는 api입니다.",)
def patch_record(rec_id: int, record: RecordPatch, db: Session = Depends(get_db)):
    rec = db.query(Record).get(rec_id)
    if not rec: raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")
    apply_patch(rec, record.model_dump(exclude_unset=True))
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec_to_dict(rec)


# 자연어 지시로 수정 api
@router.post("/api/records/{rec_id}/agent",
             tags=["복막투석기록"],
             summary="자연어 지시로 수정",
             description="자연어 지시로 복막투석기록을 수정하는 api입니다.",)
def agent_update(rec_id: int, body: AgentIn, db: Session = Depends(get_db)):
    rec = db.query(Record).get(rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="복막투석기록을 찾을 수 없습니다.")
    patch = agent_text_to_patch(body.text)
    if not patch:
        raise HTTPException(status_code=400, detail="수정할 항목을 이해하지 못했습니다.")
    apply_patch(rec, patch)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"message": "updated", "patch": patch, "record": rec_to_dict(rec)}
