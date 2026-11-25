"""Shared helpers for the S-12 development-database scripts."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_NAME = "s2_mvp_20261125"
EMBEDDING_MODEL_VERSION = "qwen3.7-text-embedding-flash-1024-v1"
PBKDF2_ITERATIONS = 260_000

# v0.1.2 的验收口径，脚本与文档共用，避免各处写死不同数字。
EXPECTED_COUNTS = {
    "achievement": 300,
    "demand": 100,
    "enterprise": 25,
    "achievement_tag": 811,
    "achievement_extraction": 300,
    "achievement_text": 300,
    "embedding": 400,
    "demand_tag": 308,
    "eval_query": 20,
    "eval_label": 50,
}
TAG_DIMENSION_COUNTS = {
    "tech_field": 404,
    "application_scenario": 107,
    "cooperation_mode": 300,
}
EXPECTED_NEEDS_REVIEW = 61
EXPECTED_PRIMARY_TECH_FIELDS = 300
EXPECTED_USERS = 2


def load_env(path: Path | None = None) -> dict[str, str]:
    """Read the repo .env without requiring python-dotenv."""
    env_path = path or PROJECT_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def base_dsn(env: dict[str, str] | None = None) -> str:
    env = env if env is not None else load_env()
    dsn = env.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set in .env or the environment")
    return dsn


def dsn_for_db(db_name: str, env: dict[str, str] | None = None) -> str:
    """Replace only the database name, keeping host/port/user/password/query."""
    parsed = urllib.parse.urlsplit(base_dsn(env))
    if not db_name:
        raise ValueError("db_name must not be empty")
    return urllib.parse.urlunsplit(parsed._replace(path="/" + db_name))


def dsn_target(dsn: str) -> dict[str, str | int | None]:
    parsed = urllib.parse.urlsplit(dsn)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": parsed.path.lstrip("/"),
    }


def redact_dsn(dsn: str) -> str:
    parsed = urllib.parse.urlsplit(dsn)
    if not parsed.password:
        return dsn
    netloc = f"{parsed.username}:***@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urllib.parse.urlunsplit(parsed._replace(netloc=netloc))


def ensure_dev_db(db_name: str, allow_non_dev: bool = False) -> None:
    """Refuse to write outside s2_mvp_* unless the caller explicitly opts in."""
    if allow_non_dev:
        return
    if not db_name.startswith("s2_mvp_"):
        raise SystemExit(
            f"refusing to write non-development database: {db_name} "
            "(only s2_mvp_* is allowed; pass --allow-non-dev to override)"
        )


def hash_password(
    password: str,
    *,
    iterations: int = PBKDF2_ITERATIONS,
    salt_hex: str | None = None,
) -> str:
    """Return pbkdf2_sha256$iterations$salt_hex$digest_hex.

    S-11 must verify with the same format; see docs/09-项目管理/开发库与部署说明.
    """
    if not password:
        raise ValueError("password must not be empty")
    salt = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest = stored.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations_text)
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, digest)
