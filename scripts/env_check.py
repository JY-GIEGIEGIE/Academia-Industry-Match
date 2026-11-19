#!/usr/bin/env python3
"""数据侧环境自检（Python 3.11，仅用标准库）。

检查项：
  1. Python 版本 >= 3.11
  2. .env 是否存在、必需变量是否齐全（不回显 key）
  3. 百炼对话模型可用（默认 qwen3.8-flash）
  4. 百炼 embedding 可用且维度 = 1024；query/document 模式生效
  5. PostgreSQL 16 + pgvector 0.8.x 可连接（优先 psycopg，其次 docker compose exec）

用法：
  python scripts/env_check.py
  python scripts/env_check.py --skip-api
  python scripts/env_check.py --skip-db
  python scripts/env_check.py --json

退出码：0 = 无 FAIL；1 = 至少一个 FAIL。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TIMEOUT = 60

REQUIRED_VARS = [
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "EMBEDDING_MODEL_VERSION",
    "DATABASE_URL",
]


class Checker:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(self, name: str, status: str, detail: str, required: bool = True) -> None:
        self.results.append(
            {"name": name, "status": status, "detail": detail, "required": required}
        )

    def summary(self) -> dict:
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
        for r in self.results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        failed = [r for r in self.results if r["status"] == "FAIL"]
        return {"counts": counts, "ok": not failed}


def load_dotenv(path: Path, override: bool = False) -> None:
    """极简 .env 解析；不覆盖已存在的环境变量（除非 override=True）。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 12:
        return "***"
    return value[:6] + "..." + value[-4:]


def http_json(
    url: str, payload: dict | None = None, api_key: str | None = None, timeout: int = TIMEOUT
) -> tuple[int | None, dict]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "aim-env-check/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {"raw": body[:500]}
        return exc.code, parsed
    except Exception as exc:  # noqa: BLE001 - 自检脚本需要把网络异常转成报告
        return None, {"error": f"{type(exc).__name__}: {exc}"}


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def check_python(c: Checker) -> None:
    v = sys.version_info
    status = "PASS" if v >= (3, 11) else "FAIL"
    c.add("Python 版本", status, f"{v.major}.{v.minor}.{v.micro}（要求 >= 3.11）")


def check_env_file(c: Checker) -> None:
    if ENV_PATH.exists():
        c.add("配置文件", "PASS", f".env 已找到：{ENV_PATH}")
    else:
        c.add("配置文件", "FAIL", f"缺少 {ENV_PATH}；请复制 .env.example 为 .env 并填写")


def check_required_vars(c: Checker) -> list[str]:
    missing = [k for k in REQUIRED_VARS if not os.getenv(k)]
    if missing:
        c.add("必需变量", "FAIL", "缺少：" + ", ".join(missing))
        return missing
    c.add(
        "必需变量",
        "PASS",
        f"{len(REQUIRED_VARS)} 项齐全；DASHSCOPE_API_KEY={mask(os.getenv('DASHSCOPE_API_KEY', ''))}",
    )
    return []


def check_chat(c: Checker) -> None:
    base = os.environ["DASHSCOPE_BASE_URL"].rstrip("/")
    model = os.getenv("QWEN_CHAT_MODEL", "qwen3.8-flash")
    status, body = http_json(
        f"{base}/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": "只回复两个字母：OK"}],
            "max_tokens": 16,
            "temperature": 0,
        },
        os.environ["DASHSCOPE_API_KEY"],
    )
    if status == 200 and body.get("choices"):
        content = body["choices"][0].get("message", {}).get("content", "")
        c.add("百炼对话", "PASS", f"{model} 返回 {content!r}")
    else:
        c.add("百炼对话", "FAIL", f"{model} HTTP {status}: {str(body)[:300]}")


def check_embedding(c: Checker) -> None:
    base = os.environ["DASHSCOPE_BASE_URL"].rstrip("/")
    model = os.environ["EMBEDDING_MODEL"]
    try:
        dim = int(os.environ["EMBEDDING_DIM"])
    except ValueError:
        c.add("百炼向量", "FAIL", f"EMBEDDING_DIM 不是整数：{os.environ['EMBEDDING_DIM']!r}")
        return

    texts = ["硫化物固态电解质离子电导率", "锂离子电池硅碳负极循环稳定性"]
    status, body = http_json(
        f"{base}/embeddings",
        {
            "model": model,
            "input": texts,
            "dimensions": dim,
            "encoding_format": "float",
            "text_type": "document",
        },
        os.environ["DASHSCOPE_API_KEY"],
    )
    if status != 200 or "data" not in body:
        c.add("百炼向量", "FAIL", f"{model} HTTP {status}: {str(body)[:300]}")
        return

    vectors = [item.get("embedding", []) for item in body["data"]]
    if len(vectors) != len(texts):
        c.add("百炼向量", "FAIL", f"返回 {len(vectors)} 条，期望 {len(texts)} 条")
        return
    actual_dims = {len(v) for v in vectors}
    if actual_dims != {dim}:
        c.add("百炼向量", "FAIL", f"维度 {sorted(actual_dims)}，期望 {dim}")
        return
    c.add(
        "百炼向量",
        "PASS",
        f"{model} batch={len(texts)} dim={dim} usage={body.get('usage')}",
    )

    # query/document 是否真的区分：同一文本两种 text_type 的余弦应明显 < 1。
    status_q, body_q = http_json(
        f"{base}/embeddings",
        {
            "model": model,
            "input": [texts[0]],
            "dimensions": dim,
            "encoding_format": "float",
            "text_type": "query",
        },
        os.environ["DASHSCOPE_API_KEY"],
    )
    if status_q == 200 and body_q.get("data"):
        cos = cosine(vectors[0], body_q["data"][0]["embedding"])
        if cos < 0.999:
            c.add("query/document 区分", "PASS", f"cos={cos:.4f}（text_type 生效）")
        else:
            c.add(
                "query/document 区分",
                "WARN",
                f"cos={cos:.4f}，text_type 可能未生效；全组必须统一 embedding 用法",
                required=False,
            )
    else:
        c.add(
            "query/document 区分",
            "WARN",
            f"HTTP {status_q}: {str(body_q)[:200]}",
            required=False,
        )


def db_params() -> tuple[str, str, int, str]:
    url = os.getenv("DATABASE_URL", "")
    parsed = urlparse(url)
    if parsed.scheme in ("postgres", "postgresql") and parsed.hostname:
        user = parsed.username or os.getenv("POSTGRES_USER", "aim")
        host = parsed.hostname
        port = parsed.port or int(os.getenv("POSTGRES_PORT", "5432"))
        dbname = (parsed.path or "/").lstrip("/") or os.getenv("POSTGRES_DB", "academia_industry_match")
        return user, host, port, dbname
    return (
        os.getenv("POSTGRES_USER", "aim"),
        os.getenv("POSTGRES_HOST", "127.0.0.1"),
        int(os.getenv("POSTGRES_PORT", "5432")),
        os.getenv("POSTGRES_DB", "academia_industry_match"),
    )


def db_version_via_psycopg(dsn: str) -> tuple[str | None, str]:
    try:
        import psycopg  # type: ignore
    except ImportError:
        return None, "psycopg 未安装"
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select current_setting('server_version_num'), "
                    "coalesce((select extversion from pg_extension where extname='vector'), '')"
                )
                row = cur.fetchone()
                return f"{row[0]}|{row[1]}", "psycopg"
    except Exception as exc:  # noqa: BLE001
        return None, f"psycopg 连接失败：{type(exc).__name__}: {exc}"


def db_version_via_docker() -> tuple[str | None, str]:
    user, _host, _port, dbname = db_params()
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        user,
        "-d",
        dbname,
        "-tAc",
        "select current_setting('server_version_num') || '|' || "
        "coalesce((select extversion from pg_extension where extname='vector'), '')",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        return None, "未找到 docker 命令"
    except subprocess.TimeoutExpired:
        return None, "docker compose exec 超时"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")[:300]
        return None, f"docker compose exec 失败：{detail}"
    line = (proc.stdout or "").strip().splitlines()
    return (line[-1] if line else None), "docker compose exec"


def check_db(c: Checker) -> None:
    dsn = os.getenv("DATABASE_URL", "")
    raw, source = db_version_via_psycopg(dsn) if dsn else (None, "缺少 DATABASE_URL")
    if raw is None:
        raw, source = db_version_via_docker()
    if raw is None:
        c.add(
            "数据库",
            "FAIL",
            f"{source}；先运行 docker compose up -d db，并确认 5432 端口可用",
        )
        return
    try:
        version_num, extversion = raw.split("|", 1)
        major = int(version_num) // 10000
    except ValueError:
        c.add("数据库", "FAIL", f"无法解析版本输出：{raw!r}（来源：{source}）")
        return

    if major != 16:
        c.add("数据库", "FAIL", f"PostgreSQL {major}（要求 16；来源：{source}）")
        return
    if not extversion:
        c.add(
            "数据库",
            "FAIL",
            "pgvector 扩展未安装；执行 CREATE EXTENSION vector; 或重建 DB volume",
        )
        return
    if not extversion.startswith("0.8"):
        c.add("数据库", "FAIL", f"pgvector {extversion}（要求 0.8.x）")
        return
    c.add(
        "数据库",
        "PASS",
        f"PostgreSQL {major} + pgvector {extversion}（检查方式：{source}）",
    )


def main() -> int:
    # Windows 控制台默认可能是 GBK；统一成 UTF-8，避免中文报告乱码。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="数据侧环境自检")
    parser.add_argument("--skip-api", action="store_true", help="跳过百炼 API 检查")
    parser.add_argument("--skip-db", action="store_true", help="跳过数据库检查")
    parser.add_argument("--json", action="store_true", help="只输出 JSON 报告")
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    c = Checker()

    check_python(c)
    check_env_file(c)
    missing = check_required_vars(c)

    if args.skip_api:
        c.add("百炼 API", "SKIP", "按 --skip-api 跳过", required=False)
    elif missing:
        c.add("百炼 API", "SKIP", "缺少必需变量，无法检查", required=False)
    else:
        check_chat(c)
        check_embedding(c)

    if args.skip_db:
        c.add("数据库", "SKIP", "按 --skip-db 跳过", required=False)
    elif "DATABASE_URL" in missing:
        c.add("数据库", "SKIP", "缺少 DATABASE_URL，无法检查", required=False)
    else:
        check_db(c)

    summary = c.summary()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "env_file": str(ENV_PATH),
        "python": sys.version.split()[0],
        "results": c.results,
        "summary": summary,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== 数据侧环境自检 ===")
        print(f".env: {ENV_PATH}")
        for r in c.results:
            print(f"[{r['status']}] {r['name']}: {r['detail']}")
        counts = summary["counts"]
        print(
            f"\n结果：{counts.get('PASS', 0)} PASS / "
            f"{counts.get('FAIL', 0)} FAIL / {counts.get('WARN', 0)} WARN / "
            f"{counts.get('SKIP', 0)} SKIP"
        )
        if summary["ok"]:
            print("环境就绪：可以开始数据侧工作。")
        else:
            print("环境未就绪：先解决上面的 FAIL 项。")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
