#!/usr/bin/env python3
"""评测预标 / 合并 / kappa 的离线单元测试（不联网、不花 token）。"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import scripts.data.adjudicate_eval as ae  # noqa: E402
import scripts.data.apply_eval_annotations as ap  # noqa: E402
import scripts.data.eval_kappa as ek  # noqa: E402
import scripts.data.prelabel_eval as pe  # noqa: E402


class ParseQueryResponseTest(unittest.TestCase):
    def test_valid_response(self):
        raw = {
            "grades": [
                {"achievement_id": "ach_1", "grade": 2, "confidence": 0.9,
                 "evidence": "high ionic conductivity", "rationale": "同领域"},
                {"achievement_id": "ach_2", "grade": 0, "confidence": 0.8,
                 "evidence": "different topic", "rationale": "不同领域"},
            ]
        }
        normalized, missing, errors = pe.parse_query_response(raw, ["ach_1", "ach_2"])
        self.assertEqual(errors, [])
        self.assertEqual(missing, [])
        self.assertEqual([item["grade"] for item in normalized], [2, 0])

    def test_missing_invalid_and_extra(self):
        raw = {
            "grades": [
                {"achievement_id": "ach_1", "grade": 3},
                {"achievement_id": "ach_extra", "grade": 1},
            ]
        }
        normalized, missing, errors = pe.parse_query_response(raw, ["ach_1", "ach_2"])
        self.assertEqual(normalized, [])
        self.assertEqual(missing, ["ach_1", "ach_2"])
        self.assertEqual(len(errors), 2)

    def test_duplicate_id(self):
        raw = {
            "grades": [
                {"achievement_id": "ach_1", "grade": 1},
                {"achievement_id": "ach_1", "grade": 2},
            ]
        }
        normalized, missing, errors = pe.parse_query_response(raw, ["ach_1"])
        self.assertEqual(len(normalized), 1)
        self.assertEqual(missing, [])
        self.assertTrue(any("重复" in error for error in errors))


class EvidenceAndPriorityTest(unittest.TestCase):
    def test_grounding_normalizes_unicode_dash(self):
        self.assertTrue(
            pe.evidence_grounded(
                "Ni‐Rich Cathode Materials",
                "Phase Behavior of Ni-Rich Cathode Materials",
                "",
            )
        )

    def test_grounding_rejects_short_or_absent(self):
        self.assertFalse(pe.evidence_grounded("short", "x", "y"))
        self.assertFalse(pe.evidence_grounded("a totally absent sentence", "title", "abstract"))

    def test_priority(self):
        self.assertEqual(pe.review_priority(1, 0.95, "evidence quote", True), "high")
        self.assertEqual(pe.review_priority(0, 0.95, "evidence quote", True), "normal")
        self.assertEqual(pe.review_priority(0, 0.3, "evidence quote", True), "high")
        self.assertEqual(pe.review_priority(0, 0.95, "", True), "high")


class ApplyQueryTest(unittest.TestCase):
    def setUp(self):
        self.templates = [
            {
                "query_id": "q01",
                "query_text": "q",
                "query_language": "zh",
                "query_type": "zh_business",
                "target_tech_field": "electrolyte",
                "candidate_achievement_ids": ["ach_1", "ach_2", "ach_3"],
                "notes": "原始备注",
            }
        ]
        self.review = [
            {"query_id": "q01", "achievement_id": "ach_1", "llm_grade": "2",
             "human_grade": "1", "human_note": "指标不冲突，场景匹配"},
            {"query_id": "q01", "achievement_id": "ach_2", "llm_grade": "0",
             "human_grade": "", "human_note": ""},
            {"query_id": "q01", "achievement_id": "ach_3", "llm_grade": "1",
             "human_grade": "", "human_note": ""},
        ]

    def test_aggregate_with_llm_fallback(self):
        rows, detail, errors, stats = ap.build_query_rows(
            self.templates,
            self.review,
            annotator="tester",
            use_llm_when_blank=True,
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["relevance_grades"], {"ach_1": 1, "ach_2": 0, "ach_3": 1})
        self.assertEqual(row["relevant_achievement_ids"], ["ach_1", "ach_3"])
        self.assertIn("原始备注", row["notes"])
        self.assertIn("指标不冲突", row["notes"])
        csv_row = ap.query_csv_row(row)
        self.assertEqual(csv_row["relevance_grades"], "ach_1:1;ach_2:0;ach_3:1")
        self.assertEqual(csv_row["relevant_achievement_ids"], "ach_1;ach_3")
        self.assertEqual(stats["human_overrides"], 1)
        self.assertEqual(stats["llm_accepted"], 2)

    def test_blank_without_fallback_is_error(self):
        rows, detail, errors, stats = ap.build_query_rows(
            self.templates,
            self.review,
            annotator="tester",
            use_llm_when_blank=False,
        )
        self.assertEqual(rows, [])
        self.assertTrue(any("human_grade 为空" in error for error in errors))


class ApplyQueryFinalTest(unittest.TestCase):
    def setUp(self):
        self.templates = [
            {
                "query_id": "q01",
                "query_text": "q",
                "query_language": "zh",
                "query_type": "zh_business",
                "target_tech_field": "electrolyte",
                "candidate_achievement_ids": ["ach_1", "ach_2", "ach_3"],
                "notes": "模板备注",
            }
        ]
        self.final = [
            {
                "query_id": "q01",
                "query_text": "q",
                "query_language": "zh",
                "query_type": "zh_business",
                "target_tech_field": "electrolyte",
                "candidate_achievement_ids": "ach_1;ach_2;ach_3",
                "relevant_achievement_ids": "ach_1;ach_3",
                "relevance_grades": "ach_1:2;ach_3:1",
                "annotator": "黄欣悦",
                "notes": "人工备注",
            }
        ]

    def test_human_final_rows(self):
        rows, errors, stats = ap.build_query_rows_from_final(
            self.templates, self.final, annotator="fallback"
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relevance_grades"], {"ach_1": 2, "ach_3": 1})
        self.assertEqual(rows[0]["relevant_achievement_ids"], ["ach_1", "ach_3"])
        self.assertEqual(rows[0]["annotator"], "黄欣悦")
        self.assertEqual(rows[0]["notes"], "人工备注")
        self.assertEqual(stats["annotated_grades"], 2)
        self.assertEqual(stats["candidates"], 3)

    def test_relevant_list_mismatch(self):
        bad = [dict(self.final[0], relevant_achievement_ids="ach_1")]
        rows, errors, stats = ap.build_query_rows_from_final(
            self.templates, bad, annotator="fallback"
        )
        self.assertEqual(rows, [])
        self.assertTrue(any("不一致" in error for error in errors))

    def test_candidate_change(self):
        bad = [dict(self.final[0], candidate_achievement_ids="ach_1;ach_2")]
        rows, errors, stats = ap.build_query_rows_from_final(
            self.templates, bad, annotator="fallback"
        )
        self.assertEqual(rows, [])
        self.assertTrue(any("candidate_achievement_ids" in error for error in errors))

    def test_parse_grades_invalid(self):
        grades, error = ap._parse_grades_final("ach_1:3")
        self.assertEqual(grades, {})
        self.assertIsNotNone(error)


class ApplyPairTest(unittest.TestCase):
    def test_pair_from_final(self):
        templates = [
            {
                "pair_id": "pair_001",
                "demand_id": "dem_001",
                "demand_title": "需求",
                "achievement_id": "ach_1",
                "achievement_title": "成果",
                "pair_source": "same_field",
                "hard_negative_type": "none",
            }
        ]
        final = [
            {
                "pair_id": "pair_001",
                "demand_id": "dem_001",
                "achievement_id": "ach_1",
                "relevance_grade": "1",
                "rationale": "部分相关",
                "annotator": "黄欣悦",
                "adjudication": "",
            }
        ]
        rows, errors, stats = ap.build_pair_rows_from_final(
            templates, final, annotator="fallback"
        )
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["relevance_grade"], 1)
        self.assertEqual(rows[0]["annotator"], "黄欣悦")
        self.assertEqual(stats["same_field_0"], 0)

    def test_pair_from_review_fallback(self):
        templates = [
            {
                "pair_id": "pair_001",
                "demand_id": "dem_001",
                "demand_title": "需求",
                "achievement_id": "ach_1",
                "achievement_title": "成果",
                "pair_source": "cross_field",
                "hard_negative_type": "cross_field",
            }
        ]
        review = [
            {"pair_id": "pair_001", "llm_grade": "0", "llm_rationale": "领域不同",
             "human_grade": "", "human_note": "", "adjudication": ""}
        ]
        rows, detail, errors, stats = ap.build_pair_rows_from_review(
            templates, review, annotator="tester", use_llm_when_blank=True
        )
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["relevance_grade"], 0)
        self.assertEqual(rows[0]["rationale"], "领域不同")
        self.assertEqual(stats["llm_accepted"], 1)


class HardTimeoutTest(unittest.TestCase):
    class SlowClient:
        def chat_json(self, messages, *, model=None, max_tokens=None, timeout=None):
            time.sleep(0.5)
            return {"ok": True}

    class FastClient:
        def chat_json(self, messages, *, model=None, max_tokens=None, timeout=None):
            return {"ok": True}

    def test_timeout_raises(self):
        with self.assertRaises(TimeoutError):
            pe._call_chat_json(
                self.SlowClient(), [], model=None, max_tokens=1, timeout=0.05
            )

    def test_values_pass_through(self):
        result = pe._call_chat_json(
            self.FastClient(), [], model=None, max_tokens=1, timeout=1
        )
        self.assertEqual(result, {"ok": True})


class AdjudicationClassifyTest(unittest.TestCase):
    def test_q2_adjacent(self):
        row = {"kind": "query", "human_grade": "0", "user_grade": "1",
               "title": "Graphite anode", "user_note": "领域相邻且可迁移"}
        self.assertEqual(ae.classify(row), ("Q2", 1))

    def test_q1a_hard_constraint(self):
        row = {"kind": "query", "human_grade": "1", "user_grade": "2",
               "title": "Ni-rich cathode", "user_note": "摘要未限定晶粒形态"}
        self.assertEqual(ae.classify(row), ("Q1a", 1))

    def test_q1b_review(self):
        row = {"kind": "query", "human_grade": "1", "user_grade": "2",
               "title": "A Review on Hard Carbon", "user_note": "综述"}
        self.assertEqual(ae.classify(row), ("Q1b", 1))

    def test_q3_inference(self):
        row = {"kind": "query", "human_grade": "0", "user_grade": "2",
               "title": "PDOL electrolyte", "user_note": "推断"}
        self.assertEqual(ae.classify(row), ("Q3", 1))

    def test_pair_rules(self):
        for pair_id, expected in (("pair_021", ("P1", 1)),
                                  ("pair_022", ("P2", 0)),
                                  ("pair_025", ("P3", 1))):
            row = {"kind": "pair", "id": pair_id, "human_grade": "1",
                   "user_grade": "2"}
            self.assertEqual(ae.classify(row), expected)

    def test_parse_grades(self):
        self.assertEqual(
            ae.parse_grades("ach_1:2;ach_3:1;bad"),
            {"ach_1": 2, "ach_3": 1},
        )


class KappaTest(unittest.TestCase):
    def test_perfect_agreement(self):
        result = ek.weighted_kappa([0, 1, 2, 1, 0], [0, 1, 2, 1, 0])
        self.assertEqual(result["kappa"], 1.0)
        self.assertEqual(result["observed_agreement"], 1.0)

    def test_complete_disagreement(self):
        result = ek.weighted_kappa([0, 0, 0], [1, 1, 1])
        self.assertEqual(result["kappa"], 0.0)

    def test_no_variance_is_undefined(self):
        result = ek.weighted_kappa([0, 0, 0], [0, 0, 0])
        self.assertIsNone(result["kappa"])
        self.assertTrue(result["note"])

    def test_blank_as_zero(self):
        row = {"human_grade": ""}
        self.assertEqual(
            ek.secondary_grade(row, blank_as_zero=True), 0
        )
        self.assertIsNone(ek.secondary_grade(row, blank_as_zero=False))

    def test_gbk_csv_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as handle:
            handle.write(
                "query_id,achievement_id,human_grade\nq01,ach_1,2\n".encode("gbk")
            )
            name = handle.name
        try:
            rows = ek.load_csv(Path(name))
            self.assertEqual(rows[0]["human_grade"], "2")
        finally:
            Path(name).unlink(missing_ok=True)

    def test_expand_query_rows(self):
        rows = [
            {
                "query_id": "q01",
                "candidate_achievement_ids": "ach_1;ach_2;ach_3",
                "relevance_grades": "ach_1:2;ach_3:1",
            }
        ]
        expanded = ek.expand_query_rows(rows)
        self.assertEqual(len(expanded), 3)
        self.assertEqual(
            {row["achievement_id"]: row["human_grade"] for row in expanded},
            {"ach_1": 2, "ach_2": 0, "ach_3": 1},
        )

    def test_expand_passthrough_per_candidate(self):
        rows = [{"query_id": "q01", "achievement_id": "ach_1", "human_grade": 1}]
        self.assertEqual(ek.expand_query_rows(rows), rows)

    def test_secondary_llm_fallback(self):
        row = {"human_grade": "", "llm_grade": "2"}
        self.assertEqual(
            ek.secondary_grade(row, blank_as_zero=True, use_llm_when_blank=True),
            2,
        )
        self.assertEqual(
            ek.secondary_grade(row, blank_as_zero=True, use_llm_when_blank=False),
            0,
        )


if __name__ == "__main__":
    unittest.main()
