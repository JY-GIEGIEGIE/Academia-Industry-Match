#!/usr/bin/env python3
"""embed.py 与 evaluate.py 的离线单元测试（mock 客户端，不联网、不花 token）。

CI 运行：python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import scripts.data.embed as embed_mod  # noqa: E402
import scripts.data.evaluate as eval_mod  # noqa: E402

EMB_MODEL = "qwen3.7-text-embedding-flash"


def make_vec(dim: int = 1024) -> list[float]:
    return [1.0] * dim


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class FakeEmbedClient:
    embedding_model = EMB_MODEL
    embedding_dim = 1024

    def __init__(self):
        self.calls = []

    def embed_texts(self, texts, text_type="document", dimensions=None):
        self.calls.append({"text_type": text_type, "n": len(texts), "dimensions": dimensions})
        return [make_vec() for _ in texts]


class FakeEvalClient:
    embedding_model = EMB_MODEL
    embedding_dim = 1024

    def __init__(self, n=1):
        self.n = n

    def embed_texts(self, texts, text_type="query", dimensions=None):
        return [make_vec() for _ in texts]


def embed_args(**kw) -> argparse.Namespace:
    d = dict(profiles=None, demands=None, output=None, version="v0.1-thin", run_id="test-embed")
    d.update(kw)
    return argparse.Namespace(**d)


def eval_args(**kw) -> argparse.Namespace:
    d = dict(queries=None, embeddings=None, labels=None, achievements=None,
             output=None, version="v0.1-thin", query_vectors=None,
             top_k=10, details_out=None)
    d.update(kw)
    return argparse.Namespace(**d)


# ---------------------------------------------------------------------------
# embed.py
# ---------------------------------------------------------------------------
class EmbedSplitTest(unittest.TestCase):
    def test_achievements_document_demands_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profiles = tmp_path / "profiles.jsonl"
            demands = tmp_path / "demands.jsonl"
            write_jsonl(profiles, [
                {"achievement_id": "ach_1", "text": "硫化物固态电解质", "text_hash": "h1"},
            ])
            write_jsonl(demands, [
                {"demand_id": "dem_1", "title": "固态电解质中试",
                 "pain_point": "电导率不足", "expected_solution": "中试放大"},
            ])

            client = FakeEmbedClient()
            with mock.patch.object(embed_mod, "DashScopeClient", return_value=client), \
                 mock.patch.object(embed_mod, "MANIFEST_DIR", tmp_path / "manifests"):
                rc = embed_mod.run(embed_args(profiles=str(profiles), demands=str(demands),
                                              output=str(tmp_path / "emb.jsonl")))

            self.assertEqual(rc, 0)
            types = sorted(c["text_type"] for c in client.calls)
            self.assertEqual(types, ["document", "query"])  # 成果 document，需求 query


class EmbedCoverageTest(unittest.TestCase):
    def test_missing_profile_lowers_coverage_and_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profiles = tmp_path / "profiles.jsonl"
            demands = tmp_path / "demands.jsonl"
            write_jsonl(profiles, [
                {"achievement_id": "ach_1", "text": "有画像", "text_hash": "h1"},
                {"achievement_id": "ach_2", "text": ""},  # 空画像
            ])
            write_jsonl(demands, [
                {"demand_id": "dem_1", "title": "t", "pain_point": "p", "expected_solution": "e"},
            ])

            client = FakeEmbedClient()
            with mock.patch.object(embed_mod, "DashScopeClient", return_value=client), \
                 mock.patch.object(embed_mod, "MANIFEST_DIR", tmp_path / "manifests"):
                rc = embed_mod.run(embed_args(profiles=str(profiles), demands=str(demands),
                                              output=str(tmp_path / "emb.jsonl")))

            self.assertNotEqual(rc, 0)  # 覆盖率不足 → 非 0
            manifest = json.loads((tmp_path / "manifests" / "embed_test-embed.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["profile_missing"], 1)
            self.assertLess(manifest["coverage"], 1.0)


# ---------------------------------------------------------------------------
# evaluate.py：向量校验
# ---------------------------------------------------------------------------
class EvalVectorValidationTest(unittest.TestCase):
    def test_rejects_wrong_dim(self):
        emb = [{"object_type": "achievement", "object_id": "a", "text_type": "capability_profile",
                "dim": 768, "vector": make_vec(768), "model": EMB_MODEL}]
        with self.assertRaises(ValueError):
            eval_mod._load_ach_vectors(emb)

    def test_rejects_mixed_models(self):
        emb = [
            {"object_type": "achievement", "object_id": "a", "text_type": "capability_profile",
             "dim": 1024, "vector": make_vec(), "model": "m1"},
            {"object_type": "achievement", "object_id": "b", "text_type": "capability_profile",
             "dim": 1024, "vector": make_vec(), "model": "m2"},
        ]
        with self.assertRaises(ValueError):
            eval_mod._load_ach_vectors(emb)

    def test_skips_non_capability_profile(self):
        emb = [
            {"object_type": "achievement", "object_id": "a", "text_type": "abstract",
             "dim": 1024, "vector": make_vec(), "model": EMB_MODEL},
            {"object_type": "achievement", "object_id": "b", "text_type": "capability_profile",
             "dim": 1024, "vector": make_vec(), "model": EMB_MODEL},
        ]
        vectors, models = eval_mod._load_ach_vectors(emb)
        self.assertEqual(set(vectors), {"b"})


# ---------------------------------------------------------------------------
# evaluate.py：BM25 / 指标 / 解析
# ---------------------------------------------------------------------------
class EvalBm25Test(unittest.TestCase):
    def test_unknown_candidate_skipped(self):
        bm25 = eval_mod.BM25(["硫化物固态电解质中试放大"])
        index_of = {"a": 0}
        ranked = eval_mod._rank_b0(["a", "b_unknown"], bm25, index_of, "硫化物电解质")
        self.assertEqual(ranked, ["a"])  # 未知候选被跳过，不落到第 0 篇


class EvalMetricsTest(unittest.TestCase):
    def test_recall_precision_mrr(self):
        ranked = ["a", "x", "b", "y"]
        relevant = {"a", "b"}
        self.assertEqual(eval_mod._recall_at_k(ranked, relevant, 10), 1.0)
        self.assertEqual(eval_mod._precision_at_k(ranked, relevant, 5), 0.4)
        self.assertEqual(eval_mod._precision_at_k(ranked, relevant, 2), 0.5)
        self.assertEqual(eval_mod._mrr(ranked, relevant), 1.0)

    def test_ndcg_perfect_and_degraded(self):
        graded = {"a": 2, "b": 1}
        self.assertAlmostEqual(eval_mod._ndcg_at_k(["a", "b"], graded, 10), 1.0)
        self.assertLess(eval_mod._ndcg_at_k(["b", "a"], graded, 10), 1.0)

    def test_recall_no_relevant_is_zero(self):
        self.assertEqual(eval_mod._recall_at_k(["a"], set(), 10), 0.0)


class EvalParseTest(unittest.TestCase):
    def test_restrict_graded_to_candidates(self):
        graded = {"a": 2, "b": 1, "c": 2}
        self.assertEqual(eval_mod._restrict_graded(graded, ["a", "b"]), {"a": 2, "b": 1})


# ---------------------------------------------------------------------------
# evaluate.py：无标注退出码
# ---------------------------------------------------------------------------
class EmbedExpectedCountTest(unittest.TestCase):
    def test_expected_count_mismatch_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profiles = tmp_path / "profiles.jsonl"
            demands = tmp_path / "demands.jsonl"
            write_jsonl(profiles, [{"achievement_id": "ach_1", "text": "画像"}])
            write_jsonl(demands, [{"demand_id": "dem_1", "title": "t"}])
            rc = embed_mod.run(embed_args(profiles=str(profiles), demands=str(demands),
                                          output=str(tmp_path / "emb.jsonl"),
                                          expected_achievements=2, expected_demands=1))
            self.assertNotEqual(rc, 0)


class EvalB2AnyTagTest(unittest.TestCase):
    def test_secondary_tech_field_is_eligible_for_b2(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            queries = tmp_path / "queries.jsonl"
            embeddings = tmp_path / "embeddings.jsonl"
            labels = tmp_path / "labels.jsonl"
            achievements = tmp_path / "achievements.jsonl"
            write_jsonl(queries, [{
                "query_id": "q1", "query_text": "液流电池膜", "target_tech_field": "flow_battery",
                "candidate_achievement_ids": ["ach_1"], "relevant_achievement_ids": ["ach_1"],
                "relevance_grades": {"ach_1": 1},
            }])
            write_jsonl(embeddings, [{
                "object_type": "achievement", "object_id": "ach_1",
                "text_type": "capability_profile", "dim": 1024,
                "vector": make_vec(), "model": EMB_MODEL,
            }])
            write_jsonl(labels, [{
                "achievement_id": "ach_1",
                "tags": [
                    {"dimension": "tech_field", "code": "separator", "is_primary": True},
                    {"dimension": "tech_field", "code": "flow_battery", "is_primary": False},
                ],
                "extraction": {"trl": 3},
            }])
            write_jsonl(achievements, [{
                "achievement_id": "ach_1", "title_original": "flow battery membrane",
                "abstract_original": "membrane",
            }])
            client = FakeEvalClient()
            with mock.patch.object(eval_mod, "DashScopeClient", return_value=client):
                rc = eval_mod.run(eval_args(
                    queries=str(queries), embeddings=str(embeddings), labels=str(labels),
                    achievements=str(achievements), output=str(tmp_path / "baseline.md"),
                    query_vectors=str(tmp_path / "qv.jsonl"),
                    details_out=str(tmp_path / "top10.csv"),
                ))
            self.assertEqual(rc, 0)
            rows = (tmp_path / "top10.csv").read_text(encoding="utf-8").splitlines()
            self.assertTrue(any("B2,1,ach_1" in line for line in rows))
            self.assertFalse(any("B2-primary,1,ach_1" in line for line in rows))


class EvalRunTest(unittest.TestCase):
    def _setup_files(self, tmp_path: Path, annotated: bool):
        queries = tmp_path / "queries.jsonl"
        embeddings = tmp_path / "embeddings.jsonl"
        labels = tmp_path / "labels.jsonl"
        achievements = tmp_path / "achievements.jsonl"
        if annotated:
            q = {"query_id": "q1", "query_text": "固态电解质", "target_tech_field": "electrolyte",
                 "candidate_achievement_ids": ["ach_1"],
                 "relevant_achievement_ids": "ach_1", "relevance_grades": "ach_1:2"}
        else:
            q = {"query_id": "q1", "query_text": "固态电解质", "target_tech_field": "electrolyte",
                 "candidate_achievement_ids": ["ach_1"],
                 "relevant_achievement_ids": "", "relevance_grades": ""}
        write_jsonl(queries, [q])
        write_jsonl(embeddings, [
            {"object_type": "achievement", "object_id": "ach_1", "text_type": "capability_profile",
             "dim": 1024, "vector": make_vec(), "model": EMB_MODEL},
        ])
        write_jsonl(labels, [
            {"achievement_id": "ach_1",
             "tags": [{"dimension": "tech_field", "code": "electrolyte", "is_primary": True}]},
        ])
        write_jsonl(achievements, [
            {"achievement_id": "ach_1", "title_original": "solid electrolyte",
             "abstract_original": "a sulfide solid electrolyte"},
        ])
        return queries, embeddings, labels, achievements

    def test_no_annotation_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            queries, embeddings, labels, achievements = self._setup_files(tmp_path, annotated=False)
            client = FakeEvalClient()
            with mock.patch.object(eval_mod, "DashScopeClient", return_value=client):
                rc = eval_mod.run(eval_args(queries=str(queries), embeddings=str(embeddings),
                                            labels=str(labels), achievements=str(achievements),
                                            output=str(tmp_path / "baseline.md"),
                                            query_vectors=str(tmp_path / "qv.jsonl"),
                                            details_out=str(tmp_path / "top10.csv")))
            self.assertNotEqual(rc, 0)

    def test_annotated_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            queries, embeddings, labels, achievements = self._setup_files(tmp_path, annotated=True)
            client = FakeEvalClient()
            with mock.patch.object(eval_mod, "DashScopeClient", return_value=client):
                rc = eval_mod.run(eval_args(queries=str(queries), embeddings=str(embeddings),
                                            labels=str(labels), achievements=str(achievements),
                                            output=str(tmp_path / "baseline.md"),
                                            query_vectors=str(tmp_path / "qv.jsonl"),
                                            details_out=str(tmp_path / "top10.csv")))
            self.assertEqual(rc, 0)
            detail_rows = (tmp_path / "top10.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(detail_rows), 5)  # header + 4 baselines × 1 candidate


if __name__ == "__main__":
    unittest.main()
