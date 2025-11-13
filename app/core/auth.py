from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.db_models.user import User

import base64

bearer_scheme = HTTPBearer()


# 토큰에서 사용자 ID 추출
def get_user_from_token(token: str) -> int:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보를 확인할 수 없습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # 토큰 디코딩 및 검증
        payload = jwt.decode(token, base64.b64decode(settings.JWT_SECRET_KEY), algorithms=[settings.JWT_ALGORITHM])

        user_id_str: str = payload.get("userId")
        if user_id_str is None:
            raise credentials_exception

        return int(user_id_str)

    except (JWTError, ValueError, TypeError) as e:
        print(f"\n[DEBUG] JWTError 발생: {e}")
        raise credentials_exception


# 활성 사용자 객체를 반환
def get_current_active_user(db: Session = Depends(get_db), token: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> User:
    # 토큰에서 사용자 ID 추출
    user_id = get_user_from_token(token.credentials)

    # DB에서 사용자 조회
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="인증된 사용자를 찾을 수 없습니다."
        )

    return user