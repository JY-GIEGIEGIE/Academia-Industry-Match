# ============================================================
# PostgreSQL 数据库连接与会话管理
#
# 功能说明：
# 1. 从 .env 读取 PostgreSQL 数据库连接配置
# 2. 使用 SQLAlchemy 2 和 psycopg 建立数据库连接
# 3. 启用 pool_pre_ping 检测失效连接
# 4. 创建统一的数据库 Session 工厂
# 5. 通过 FastAPI Depends 提供数据库会话
# 6. 在请求结束后自动关闭会话，释放连接资源
#
# 开发数据库：s2_mvp_20261125
# ============================================================

import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

database_name = urlparse(DATABASE_URL).path.lstrip("/")
if not database_name.startswith("s2_mvp_"):
    raise RuntimeError(
        "DATABASE_URL must point to an s2_mvp_* development database; "
        f"got {database_name or '<unknown>'}"
    )

# SQLAlchemy requires the psycopg driver explicitly.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
