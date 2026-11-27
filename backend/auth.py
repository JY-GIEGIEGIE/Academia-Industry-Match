# ============================================================
# 用户认证与角色权限管理
#
# 功能说明：
# 1. 提供用户登录及当前用户信息查询接口
# 2. 使用 PBKDF2-SHA256 校验数据库中的密码哈希
# 3. 登录成功后签发有效期为 2 小时的 JWT
# 4. 使用 Bearer Token 验证用户身份
# 5. 支持 researcher / enterprise 两种用户角色
# 6. 提供角色权限依赖，供发布及合作接口复用
# 7. 统一认证成功响应及 401 / 403 错误结构
#
# 数据来源：app_user
# 接口：
#   POST /api/v1/auth/login
#   GET /api/v1/auth/me
# ============================================================

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Literal
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import get_db

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not configured")

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 2

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
security = HTTPBearer(auto_error=False)


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: Literal["researcher", "enterprise"]
    display_name: str


class LoginData(BaseModel):
    token: str
    user: UserResponse


class LoginResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: LoginData


class MeResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: UserResponse


class ErrorResponse(BaseModel):
    code: int
    message: str
    data: None


AUTH_401_RESPONSE = {
    "model": ErrorResponse,
    "description": "Authentication failed or token is invalid",
    "content": {
        "application/json": {
            "example": {
                "code": 40101,
                "message": "Invalid credentials",
                "data": None,
            }
        }
    },
}

AUTH_403_RESPONSE = {
    "model": ErrorResponse,
    "description": "Authenticated user lacks permission",
    "content": {
        "application/json": {
            "example": {
                "code": 40301,
                "message": "Forbidden",
                "data": None,
            }
        }
    },
}


class LoginRequest(BaseModel):
    username: str
    password: str


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify S-12's PBKDF2-SHA256 password format."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$")

        if algorithm != "pbkdf2_sha256":
            return False

        calculated = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )

        return hmac.compare_digest(calculated.hex(), digest_hex)
    except (ValueError, AttributeError, TypeError):
        return False


def create_access_token(user_id: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(
        hours=JWT_EXPIRY_HOURS
    )

    return jwt.encode(
        {"sub": user_id, "exp": expires},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def find_user(db: Session, user_id: str):
    return db.execute(
        text("""
            SELECT user_id, username, role, display_name
            FROM app_user
            WHERE user_id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().first()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        user_id = payload.get("sub")

        if not isinstance(user_id, str) or not user_id:
            raise ValueError("Invalid token subject")

    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = find_user(db, user_id)

    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")

    return dict(user)


def require_role(role: str):
    def check_role(user: dict = Depends(get_current_user)):
        if user["role"] != role:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return check_role


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: AUTH_401_RESPONSE,
    },
)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(
        text("""
            SELECT user_id, username, password_hash, role, display_name
            FROM app_user
            WHERE username = :username
        """),
        {"username": request.username},
    ).mappings().first()

    if user is None or not verify_password(
        request.password, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    public_user = {
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
    }

    return {
        "code": 0,
        "message": "success",
        "data": {
            "token": create_access_token(user["user_id"]),
            "user": public_user,
        },
    }


@router.get(
    "/me",
    response_model=MeResponse,
    responses={
        401: AUTH_401_RESPONSE,
    },
)
def me(user: dict = Depends(get_current_user)):
    return {
        "code": 0,
        "message": "success",
        "data": user,
    }
