#!/usr/bin/env python3
"""共享百炼 / DashScope 客户端（仅标准库）。

提供给 `extract_labels.py`、`embed.py`、`evaluate.py` 等脚本复用，避免每人
各写一套 HTTP 调用。功能：

- 从仓库根目录 `.env` 读取配置（不覆盖已有环境变量）
- `chat_json` / `chat_text`：对话，JSON 模式，失败重试
- `embed_texts`：批量向量，强制 `text_type=query|document`，按 text_hash 缓存
- `rerank`：DashScope 原生 rerank 端点
- usage 日志：每次调用、耗时、token、request_id 追加到 JSONL

用法：

    from scripts.common.llm_client import chat_json, embed_texts, rerank, text_hash

    result = chat_json([{"role": "user", "content": "只输出 JSON：{\"ok\": true}"}])
    vectors = embed_texts(["硫化物固态电解质", "硅碳负极"], text_type="document")
    hits = rerank("固态电池电解质", ["硫化物固态电解质", "锂离子电池正极"])

命令行：

    python scripts/common/llm_client.py --check     # 只看配置，不调用 API
    python scripts/common/llm_client.py --demo      # 小样本跑通对话/向量/rerank
    python scripts/common/llm_client.py --clear-cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_NATIVE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_CHAT_MODEL = "qwen3.8-flash"
DEFAULT_EMBEDDING_MODEL = "qwen3.7-text-embedding-flash"
DEFAULT_EMBEDDING_DIM = 1024
DEFAULT_RERANK_MODEL = "qwen3.7-text-rerank"
DEFAULT_CACHE_PATH = ROOT / "data" / "interim" / "embedding_cache.jsonl"
DEFAULT_USAGE_LOG = ROOT / "data" / "interim" / "api_usage.jsonl"


class LlmClientError(RuntimeError):
    """客户端调用的统一异常。"""


class ConfigError(LlmClientError):
    """缺少配置（通常是 .env 未填写）。"""


class ApiError(LlmClientError):
    """HTTP/API 返回错误。"""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        body: Any = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.request_id = request_id


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env(path: Path = ENV_PATH, override: bool = False) -> None:
    """极简 .env 解析；不覆盖已有环境变量（除非 override=True）。"""
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


def text_hash(text: str) -> str:
    """归一化文本的 sha256；向量缓存的键，不存原文。"""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_json_content(content: str) -> Any:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


class DashScopeClient:
    """百炼兼容模式 + 原生 rerank 的轻量封装。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        native_base_url: str | None = None,
        chat_model: str | None = None,
        embedding_model: str | None = None,
        embedding_dim: int | None = None,
        rerank_model: str | None = None,
        cache_path: str | Path | None = None,
        usage_log: str | Path | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff: float = 2.0,
        use_cache: bool = True,
    ) -> None:
        load_env()
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        if not self.api_key:
            raise ConfigError(
                "DASHSCOPE_API_KEY 未设置；请复制 .env.example 为 .env 并填入自己的 key"
            )
        self.base_url = (
            base_url or os.getenv("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.native_base_url = (
            native_base_url or os.getenv("DASHSCOPE_NATIVE_BASE_URL", DEFAULT_NATIVE_BASE_URL)
        ).rstrip("/")
        self.chat_model = chat_model or os.getenv("QWEN_CHAT_MODEL", DEFAULT_CHAT_MODEL)
        self.embedding_model = embedding_model or os.getenv(
            "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
        )
        self.embedding_dim = int(
            embedding_dim or os.getenv("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM)
        )
        self.rerank_model = rerank_model or os.getenv("RERANK_MODEL", DEFAULT_RERANK_MODEL)
        self.cache_path = Path(
            cache_path
            if cache_path is not None
            else os.getenv("EMBEDDING_CACHE_PATH", str(DEFAULT_CACHE_PATH))
        )
        self.usage_log = Path(
            usage_log
            if usage_log is not None
            else os.getenv("API_USAGE_LOG", str(DEFAULT_USAGE_LOG))
        )
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.backoff = float(backoff)
        self.use_cache = use_cache
        self._cache: dict[str, list[float]] = self._load_cache() if use_cache else {}

    # ---------- HTTP ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "aim-llm-client/1.0",
        }

    def _post_json(self, url: str, payload: dict, timeout: float | None = None) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(raw)
            except ValueError:
                parsed = {"raw": raw[:1000]}
            message = (
                parsed.get("message") or parsed.get("error") or raw[:500]
                if isinstance(parsed, dict)
                else raw[:500]
            )
            request_id = parsed.get("request_id") if isinstance(parsed, dict) else None
            raise ApiError(
                f"HTTP {exc.code}: {message}",
                status=exc.code,
                body=parsed,
                request_id=request_id,
            ) from exc
        except urllib.error.URLError as exc:
            raise LlmClientError(f"网络错误: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LlmClientError("请求超时") from exc
        except json.JSONDecodeError as exc:
            raise LlmClientError(f"响应不是合法 JSON: {exc}") from exc

    def _request_json(
        self,
        url: str,
        payload: dict,
        *,
        operation: str,
        model: str,
        timeout: float | None = None,
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                body = self._post_json(url, payload, timeout=timeout)
                self._log_usage(
                    {
                        "ts": now_utc(),
                        "operation": operation,
                        "model": model,
                        "status": "ok",
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        "usage": body.get("usage"),
                        "request_id": body.get("request_id"),
                    }
                )
                return body
            except ApiError as exc:
                self._log_usage(
                    {
                        "ts": now_utc(),
                        "operation": operation,
                        "model": model,
                        "status": "error",
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        "http_status": exc.status,
                        "error": str(exc)[:500],
                        "request_id": exc.request_id,
                    }
                )
                last_error = exc
                retryable = exc.status in (408, 429, 500, 502, 503, 504)
                if not retryable or attempt >= self.max_retries:
                    if exc.status == 401:
                        raise ApiError(
                            f"{exc}；请检查 .env 中的 DASHSCOPE_API_KEY 是否有效",
                            status=exc.status,
                            body=exc.body,
                            request_id=exc.request_id,
                        ) from exc
                    raise
                time.sleep(self.backoff * (2**attempt) + random.uniform(0, 0.5))
            except LlmClientError as exc:
                self._log_usage(
                    {
                        "ts": now_utc(),
                        "operation": operation,
                        "model": model,
                        "status": "error",
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        "error": str(exc)[:500],
                    }
                )
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.backoff * (2**attempt) + random.uniform(0, 0.5))
        raise LlmClientError(f"请求失败: {last_error}")

    # ---------- 对话 ----------

    @staticmethod
    def _normalize_messages(messages: str | Sequence[dict]) -> list[dict]:
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]
        out = list(messages)
        if not out:
            raise ValueError("messages 不能为空")
        for msg in out:
            if "role" not in msg or "content" not in msg:
                raise ValueError("messages 每项必须包含 role 和 content")
        return out

    def _chat(
        self,
        messages: str | Sequence[dict],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        enable_thinking: bool,
        response_format: dict | None,
        timeout: float | None,
        **kwargs: Any,
    ) -> tuple[str, dict]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._normalize_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "enable_thinking": enable_thinking,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        payload.update(kwargs)
        body = self._request_json(
            f"{self.base_url}/chat/completions",
            payload,
            operation="chat_json" if response_format else "chat_text",
            model=model,
            timeout=timeout,
        )
        choices = body.get("choices") or []
        if not choices:
            raise LlmClientError(f"chat 响应无 choices: {str(body)[:500]}")
        content = (choices[0].get("message") or {}).get("content") or ""
        return content, body

    def chat_json(
        self,
        messages: str | Sequence[dict],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        enable_thinking: bool = False,
        json_retries: int = 2,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """对话并解析 JSON；模型返回非 JSON 时自动重试。"""
        model = model or self.chat_model
        base_messages = self._normalize_messages(messages)
        attempt_messages = list(base_messages)
        last_content = ""
        for attempt in range(json_retries + 1):
            content, _ = self._chat(
                attempt_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                enable_thinking=enable_thinking,
                response_format={"type": "json_object"},
                timeout=timeout,
                **kwargs,
            )
            try:
                return _parse_json_content(content)
            except (ValueError, json.JSONDecodeError) as exc:
                last_content = content
                if attempt >= json_retries:
                    raise LlmClientError(
                        f"模型未返回合法 JSON（已重试 {json_retries} 次）：{content[:500]}"
                    ) from exc
                attempt_messages = base_messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "你上一条输出不是合法 JSON。请只输出合法 JSON，不要 markdown 代码块。",
                    },
                ]
        raise LlmClientError(f"chat_json 失败：{last_content[:500]}")

    def chat_text(
        self,
        messages: str | Sequence[dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        enable_thinking: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> str:
        """普通对话；适合生成中文能力画像等自由文本。"""
        content, _ = self._chat(
            messages,
            model=model or self.chat_model,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            response_format=None,
            timeout=timeout,
            **kwargs,
        )
        return content

    # ---------- 向量 ----------

    @staticmethod
    def _cache_key(model: str, dim: int, text_type: str, digest: str) -> str:
        return f"{model}|{dim}|{text_type}|{digest}"

    def _load_cache(self) -> dict[str, list[float]]:
        cache: dict[str, list[float]] = {}
        if not self.cache_path.exists():
            return cache
        with self.cache_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    vector = record["vector"]
                    dim = int(record["dim"])
                    if not isinstance(vector, list) or len(vector) != dim:
                        continue
                    key = self._cache_key(
                        str(record["model"]),
                        dim,
                        str(record["text_type"]),
                        str(record["text_hash"]),
                    )
                    cache[key] = vector
                except (ValueError, KeyError, TypeError):
                    continue
        return cache

    def _append_cache(self, records: list[dict]) -> None:
        if not records:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def embed_texts(
        self,
        texts: str | Sequence[str],
        *,
        text_type: str = "document",
        model: str | None = None,
        dimensions: int | None = None,
        batch_size: int = 16,
        use_cache: bool | None = None,
        timeout: float | None = 120.0,
        **kwargs: Any,
    ) -> list[list[float]]:
        """批量向量。

        text_type: 入库文本用 "document"，检索 query 用 "query"。
        缓存键: model + dim + text_type + text_hash。
        """
        if isinstance(texts, str):
            texts = [texts]
        items = list(texts)
        if not items:
            return []
        if text_type not in ("query", "document"):
            raise ValueError("text_type 只能是 'query' 或 'document'")
        if not 1 <= int(batch_size) <= 25:
            raise ValueError("batch_size 需在 1..25（本环境已验证 25 条）")
        model = model or self.embedding_model
        dim = int(dimensions or self.embedding_dim)
        use_cache = self.use_cache if use_cache is None else use_cache

        results: list[list[float] | None] = [None] * len(items)
        pending: dict[str, dict[str, Any]] = {}
        cache_hits = 0
        for index, text in enumerate(items):
            digest = text_hash(text)
            key = self._cache_key(model, dim, text_type, digest)
            if use_cache and key in self._cache:
                results[index] = self._cache[key]
                cache_hits += 1
            else:
                bucket = pending.setdefault(digest, {"text": text, "indices": []})
                bucket["indices"].append(index)

        pending_items = list(pending.values())
        api_calls = 0
        for start in range(0, len(pending_items), int(batch_size)):
            batch = pending_items[start : start + int(batch_size)]
            payload: dict[str, Any] = {
                "model": model,
                "input": [item["text"] for item in batch],
                "dimensions": dim,
                "encoding_format": "float",
                "text_type": text_type,
            }
            payload.update(kwargs)
            body = self._request_json(
                f"{self.base_url}/embeddings",
                payload,
                operation="embedding",
                model=model,
                timeout=timeout,
            )
            api_calls += 1
            data = body.get("data") or []
            if len(data) != len(batch):
                raise LlmClientError(
                    f"embedding 返回 {len(data)} 条，期望 {len(batch)} 条"
                )
            cache_records: list[dict] = []
            for item, entry in zip(batch, data):
                vector = entry.get("embedding")
                if not isinstance(vector, list) or len(vector) != dim:
                    raise LlmClientError(
                        f"embedding 维度异常: "
                        f"{len(vector) if isinstance(vector, list) else type(vector)} != {dim}"
                    )
                for index in item["indices"]:
                    results[index] = vector
                if use_cache:
                    digest = text_hash(item["text"])
                    key = self._cache_key(model, dim, text_type, digest)
                    self._cache[key] = vector
                    cache_records.append(
                        {
                            "model": model,
                            "dim": dim,
                            "text_type": text_type,
                            "text_hash": digest,
                            "vector": vector,
                            "created_at": now_utc(),
                        }
                    )
            self._append_cache(cache_records)

        if any(vector is None for vector in results):
            raise LlmClientError("embedding 结果不完整")
        self._log_usage(
            {
                "ts": now_utc(),
                "operation": "embedding_summary",
                "model": model,
                "text_type": text_type,
                "dim": dim,
                "requested": len(items),
                "unique": len(pending_items),
                "api_calls": api_calls,
                "cache_hits": cache_hits,
            }
        )
        return [vector for vector in results if vector is not None]

    # ---------- Rerank ----------

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        model: str | None = None,
        top_n: int | None = None,
        return_documents: bool = False,
        timeout: float | None = 60.0,
    ) -> list[dict]:
        """DashScope 原生 rerank；返回 results 列表。"""
        model = model or self.rerank_model
        parameters: dict[str, Any] = {"return_documents": return_documents}
        if top_n is not None:
            parameters["top_n"] = int(top_n)
        payload = {
            "model": model,
            "input": {"query": query, "documents": list(documents)},
            "parameters": parameters,
        }
        body = self._request_json(
            f"{self.native_base_url}/services/rerank/text-rerank/text-rerank",
            payload,
            operation="rerank",
            model=model,
            timeout=timeout,
        )
        return list((body.get("output") or {}).get("results") or [])

    # ---------- usage ----------

    def _log_usage(self, record: dict) -> None:
        try:
            self.usage_log.parent.mkdir(parents=True, exist_ok=True)
            with self.usage_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # 日志失败不应影响主流程。
            pass

    def clear_cache(self) -> None:
        self._cache.clear()
        if self.cache_path.exists():
            self.cache_path.unlink()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="共享百炼客户端")
    parser.add_argument("--check", action="store_true", help="只打印配置，不调用 API")
    parser.add_argument("--demo", action="store_true", help="跑一个小样本对话/向量/rerank")
    parser.add_argument("--clear-cache", action="store_true", help="删除本地向量缓存")
    args = parser.parse_args(argv)

    try:
        client = DashScopeClient()
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    if args.clear_cache:
        client.clear_cache()
        print(f"已删除缓存：{client.cache_path}")
        return 0

    if not args.check and not args.demo:
        parser.print_help()
        return 0

    print(f"base_url={client.base_url}")
    print(f"chat_model={client.chat_model}")
    print(f"embedding_model={client.embedding_model} dim={client.embedding_dim}")
    print(f"rerank_model={client.rerank_model}")
    print(f"cache={client.cache_path}")
    print(f"usage_log={client.usage_log}")

    if args.demo:
        result = client.chat_json(
            '只输出 JSON：{"ok": true}，不要其他内容。', max_tokens=32
        )
        print("chat_json=", result)
        vectors = client.embed_texts(
            ["硫化物固态电解质", "硅碳负极"], text_type="document"
        )
        print(f"embedding_count={len(vectors)} dim={len(vectors[0])}")
        results = client.rerank(
            "固态电池电解质", ["硫化物固态电解质", "锂离子电池正极", "液流电池"]
        )
        print("rerank=", results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
