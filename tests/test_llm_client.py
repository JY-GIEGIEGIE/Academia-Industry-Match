"""Unit tests for scripts/common/llm_client.py (no network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.common import llm_client


def make_client(tmp: Path) -> llm_client.DashScopeClient:
    return llm_client.DashScopeClient(
        api_key="test-key",
        cache_path=tmp / "embedding_cache.jsonl",
        usage_log=tmp / "api_usage.jsonl",
        max_retries=0,
    )


class TextHashTests(unittest.TestCase):
    def test_whitespace_normalization(self) -> None:
        self.assertEqual(
            llm_client.text_hash("  solid   electrolyte \n"),
            llm_client.text_hash("solid electrolyte"),
        )

    def test_unicode_normalization(self) -> None:
        self.assertEqual(llm_client.text_hash("Ａ"), llm_client.text_hash("A"))

    def test_different_texts(self) -> None:
        self.assertNotEqual(
            llm_client.text_hash("cathode"), llm_client.text_hash("anode")
        )


class EmbeddingTests(unittest.TestCase):
    def test_batch_dedup_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            client = make_client(tmp)
            calls: list[dict] = []

            def fake_request(url, payload, *, operation, model, timeout=None):
                calls.append(payload)
                return {
                    "data": [
                        {"embedding": [0.1, 0.2, 0.3]}
                        for _ in payload["input"]
                    ],
                    "usage": {"prompt_tokens": 7},
                }

            with mock.patch.object(client, "_request_json", side_effect=fake_request):
                first = client.embed_texts(
                    ["alpha", "beta", "alpha"],
                    text_type="document",
                    dimensions=3,
                    batch_size=10,
                )
                second = client.embed_texts(
                    ["alpha", "beta"],
                    text_type="document",
                    dimensions=3,
                    batch_size=10,
                )

            # 同一批内去重，第二次全部命中缓存，只调用一次 API。
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(calls[0]["input"]), 2)
            self.assertEqual(first[0], second[0])
            self.assertEqual(first[1], second[1])
            self.assertEqual(first[2], first[0])

            cache_lines = (tmp / "embedding_cache.jsonl").read_text(
                encoding="utf-8"
            ).strip().splitlines()
            self.assertEqual(len(cache_lines), 2)
            self.assertEqual(json.loads(cache_lines[0])["dim"], 3)

            usage_lines = (tmp / "api_usage.jsonl").read_text(
                encoding="utf-8"
            ).strip().splitlines()
            self.assertTrue(
                any('"embedding_summary"' in line for line in usage_lines)
            )

    def test_query_and_document_are_separate_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            client = make_client(tmp)
            calls: list[dict] = []

            def fake_request(url, payload, *, operation, model, timeout=None):
                calls.append(payload)
                return {
                    "data": [{"embedding": [0.0, 1.0]} for _ in payload["input"]],
                    "usage": {"prompt_tokens": 3},
                }

            with mock.patch.object(client, "_request_json", side_effect=fake_request):
                client.embed_texts(
                    ["same text"], text_type="document", dimensions=2, batch_size=5
                )
                client.embed_texts(
                    ["same text"], text_type="query", dimensions=2, batch_size=5
                )

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["text_type"], "document")
            self.assertEqual(calls[1]["text_type"], "query")


class ChatJsonTests(unittest.TestCase):
    def test_parses_fenced_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            client = make_client(Path(tmp_name))
            body = {
                "choices": [
                    {"message": {"content": '```json\n{"tech_field": "electrolyte"}\n```'}}
                ],
                "usage": {},
            }
            with mock.patch.object(client, "_request_json", return_value=body):
                result = client.chat_json(
                    "Return JSON only: {\"tech_field\": \"...\"}", max_tokens=32
                )
            self.assertEqual(result, {"tech_field": "electrolyte"})

    def test_retries_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            client = make_client(Path(tmp_name))
            bodies = [
                {"choices": [{"message": {"content": "not json"}}], "usage": {}},
                {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}},
            ]
            with mock.patch.object(
                client, "_request_json", side_effect=bodies
            ) as mocked:
                result = client.chat_json("Return JSON", max_tokens=32, json_retries=1)
            self.assertEqual(result, {"ok": True})
            self.assertEqual(mocked.call_count, 2)


class RerankTests(unittest.TestCase):
    def test_returns_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            client = make_client(Path(tmp_name))
            body = {
                "output": {
                    "results": [
                        {"index": 0, "relevance_score": 0.9},
                        {"index": 1, "relevance_score": 0.1},
                    ]
                }
            }
            with mock.patch.object(client, "_request_json", return_value=body) as mocked:
                results = client.rerank("solid electrolyte", ["a", "b"], top_n=2)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["index"], 0)
            self.assertIn(
                "/services/rerank/text-rerank/text-rerank", mocked.call_args.args[0]
            )


if __name__ == "__main__":
    unittest.main()
