#!/usr/bin/env python3
"""extract_labels.py 的离线单元测试（mock chat_json，不联网、不花 token）。

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

import scripts.data.extract_labels as el  # noqa: E402

# 合法的能力画像（150—250 字内）
PROFILE_OK = "能力画像测试文本内容。" * 15  # 165 字
PROFILE_SHORT = "太短" * 5
PROFILE_LONG = PROFILE_OK * 3

ACH = {"achievement_id": "ach_test_1", "type": "article"}


def make_raw(**overrides) -> dict:
    raw = {
        "tech_fields": [
            {"code": "electrolyte", "is_primary": True, "confidence": 0.93,
             "evidence": "sulfide solid electrolyte"},
        ],
        "application_scenarios": [
            {"code": "ev_power", "confidence": 0.7, "evidence": "electric vehicles"},
        ],
        "cooperation_modes": [
            {"code": "joint_rd", "confidence": 0.4, "evidence": "potential"},
        ],
        "trl": 3,
        "trl_confidence": 0.6,
        "trl_evidence": "coin cell test",
        "material_system": "硫化物固态电解质",
        "key_metrics": [
            {"name": "ionic conductivity", "value": "10", "unit": "mS/cm", "evidence": "x"},
        ],
        "process": ["ball milling"],
        "ip_status": "unknown",
        "capability_profile_zh": PROFILE_OK,
    }
    raw.update(overrides)
    return raw


class FakeClient:
    """mock DashScopeClient：按序返回预设 chat_json 结果。"""

    chat_model = "qwen3.8-flash"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat_json(self, messages, model=None, max_tokens=None):
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        raise AssertionError("FakeClient 无更多响应")


class ValidateExtractionTest(unittest.TestCase):
    def test_primary_normalized_to_highest_confidence(self):
        raw = make_raw(
            tech_fields=[
                {"code": "electrolyte", "is_primary": False, "confidence": 0.5, "evidence": "a"},
                {"code": "anode_material", "is_primary": False, "confidence": 0.9, "evidence": "b"},
            ]
        )
        norm, illegal, review, reasons = el.validate_extraction(raw, "article")
        self.assertEqual(illegal, [])
        primary = [t["code"] for t in norm["tech_fields"] if t["is_primary"]]
        self.assertEqual(primary, ["anode_material"])
        self.assertEqual(len(norm["tech_fields"]), 2)

    def test_missing_evidence_caps_confidence_and_flags(self):
        raw = make_raw(
            application_scenarios=[{"code": "ev_power", "confidence": 0.9, "evidence": ""}]
        )
        norm, illegal, review, reasons = el.validate_extraction(raw, "article")
        self.assertTrue(review)
        self.assertIn("missing_evidence", reasons)
        self.assertLessEqual(norm["application_scenarios"][0]["confidence"], 0.4)

    def test_illegal_code_detected(self):
        raw = make_raw(tech_fields=[{"code": "WRONG_CODE", "is_primary": True,
                                     "confidence": 0.9, "evidence": "x"}])
        norm, illegal, review, reasons = el.validate_extraction(raw, "article")
        self.assertTrue(illegal)
        self.assertIn("tech_field", reasons)  # 剔除后无合法 tech_field

    def test_cooperation_confidence_capped(self):
        raw = make_raw(cooperation_modes=[{"code": "joint_rd", "confidence": 0.99, "evidence": "x"}])
        norm, _, _, _ = el.validate_extraction(raw, "article")
        self.assertLessEqual(norm["cooperation_modes"][0]["confidence"], 0.5)


class TrlDowngradeTest(unittest.TestCase):
    def test_no_evidence_nulls_trl(self):
        raw = make_raw(trl=4, trl_evidence="")
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertIsNone(norm["trl"])
        self.assertTrue(review)
        self.assertIn("trl", reasons)

    def test_paper_trl5_without_pilot_evidence_is_nulled(self):
        raw = make_raw(trl=5, trl_evidence="coin cell test")
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertIsNone(norm["trl"])
        self.assertIn("trl", reasons)

    def test_paper_trl6_with_prototype_evidence_kept(self):
        raw = make_raw(trl=6, trl_evidence="module-level prototype demonstration")
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertEqual(norm["trl"], 6)
        self.assertNotIn("trl", reasons)

    def test_paper_trl8_without_mass_production_evidence_is_nulled(self):
        raw = make_raw(trl=8, trl_evidence="coin cell test")
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertIsNone(norm["trl"])
        self.assertIn("trl", reasons)

    def test_paper_trl8_with_mass_production_evidence_kept(self):
        raw = make_raw(trl=8, trl_evidence="mass production and certification")
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertEqual(norm["trl"], 8)
        self.assertNotIn("trl", reasons)

    def test_patent_not_subject_to_paper_cap(self):
        raw = make_raw(trl=7, trl_evidence="field test")
        norm, _, review, reasons = el.validate_extraction(raw, "patent")
        self.assertEqual(norm["trl"], 7)


class ProfileTest(unittest.TestCase):
    def test_missing_profile_nulls_and_flags(self):
        raw = make_raw(capability_profile_zh="")
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertIsNone(norm["capability_profile_zh"])
        self.assertTrue(review)
        self.assertIn("profile", reasons)

    def test_short_profile_flags(self):
        raw = make_raw(capability_profile_zh=PROFILE_SHORT)
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertEqual(norm["capability_profile_zh"], PROFILE_SHORT)
        self.assertIn("profile", reasons)

    def test_long_profile_flags(self):
        raw = make_raw(capability_profile_zh=PROFILE_LONG)
        _, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertIn("profile", reasons)


class KeyMetricsTest(unittest.TestCase):
    def test_invalid_metric_dropped_and_flagged(self):
        raw = make_raw(key_metrics=[
            {"name": "capacity", "value": "210", "unit": "mAh/g", "evidence": "x"},
            {"name": "", "value": "", "unit": "", "evidence": ""},  # 非法
            "not-a-dict",  # 非法
        ])
        norm, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertEqual(len(norm["key_metrics"]), 1)
        self.assertEqual(norm["key_metrics"][0]["name"], "capacity")
        self.assertIn("key_metrics", reasons)

    def test_empty_metrics_ok(self):
        raw = make_raw(key_metrics=[])
        _, _, review, reasons = el.validate_extraction(raw, "article")
        self.assertNotIn("key_metrics", reasons)


class ExtractOneTest(unittest.TestCase):
    def test_retry_recovers_after_illegal_code(self):
        illegal = make_raw(tech_fields=[{"code": "WRONG", "is_primary": True,
                                         "confidence": 0.9, "evidence": "x"}])
        client = FakeClient([illegal, make_raw()])
        norm, raw, review, retries, reasons = el.extract_one(
            client, ACH, model="qwen3.8-flash", max_field_retries=2
        )
        self.assertEqual(retries, 1)
        self.assertFalse(review)
        self.assertEqual(client.calls, 2)

    def test_retry_exhausted_flags_review(self):
        illegal = make_raw(tech_fields=[{"code": "WRONG", "is_primary": True,
                                         "confidence": 0.9, "evidence": "x"}])
        client = FakeClient([illegal, illegal, illegal])
        norm, raw, review, retries, reasons = el.extract_one(
            client, ACH, model="qwen3.8-flash", max_field_retries=2
        )
        self.assertTrue(review)
        self.assertIn("retry_exhausted", reasons)
        self.assertEqual(retries, 2)


class BuildRecordsTest(unittest.TestCase):
    def _build(self, raw):
        norm, illegal, review, reasons = el.validate_extraction(raw, "article")
        return el.build_records(ACH, norm, raw, model="qwen3.8-flash",
                                dataset_version="v0.1-thin", run_id="test-run")

    def test_no_ids_in_output(self):
        labeled, profile, _ = self._build(make_raw())
        # tag_id / extraction_id / text_id 由导入器生成，不得出现在 JSONL 输出里
        self.assertNotIn("tag_id", labeled)
        self.assertNotIn("extraction_id", labeled["extraction"])
        for tag in labeled["tags"]:
            self.assertNotIn("tag_id", tag)
        self.assertIsNotNone(profile)
        self.assertNotIn("text_id", profile)

    def test_tag_review_status_reflects_evidence(self):
        # evidence 空（None 或空串）→ needs_review；有 evidence → pending
        raw = make_raw(
            application_scenarios=[
                {"code": "ev_power", "confidence": 0.9, "evidence": ""},   # 空串
                {"code": "grid_storage", "confidence": 0.8},               # 缺 evidence（None）
            ]
        )
        labeled, profile, review = self._build(raw)
        self.assertTrue(review)
        app_tags = {t["code"]: t for t in labeled["tags"] if t["dimension"] == "application_scenario"}
        self.assertEqual(app_tags["ev_power"]["review_status"], "needs_review")
        self.assertEqual(app_tags["grid_storage"]["review_status"], "needs_review")
        tech = next(t for t in labeled["tags"] if t["dimension"] == "tech_field")
        self.assertEqual(tech["review_status"], "pending")
        self.assertEqual(labeled["review_status"], "needs_review")
        self.assertEqual(labeled["extraction"]["review_status"], "needs_review")

    def test_profile_language_field(self):
        _, profile, _ = self._build(make_raw())
        self.assertEqual(profile["language"], "zh")


class RunIdempotencyTest(unittest.TestCase):
    def _make_args(self, **kw):
        defaults = dict(input=None, version="v0.1-thin", output_dir=None,
                        resume=False, limit=None, run_id=None, model=None,
                        max_retries=2)
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    def test_consecutive_runs_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "achievements_clean_v0.1-thin.jsonl"
            input_path.write_text(
                "\n".join(json.dumps({"achievement_id": f"ach_{i}", "type": "article",
                                      "title_original": "t", "abstract_original": "a"},
                                     ensure_ascii=False)
                          for i in (1, 2)) + "\n",
                encoding="utf-8",
            )

            client = FakeClient([make_raw(), make_raw()])
            with mock.patch.object(el, "DashScopeClient", return_value=client), \
                 mock.patch.object(el, "MANIFEST_DIR", tmp_path / "manifests"):
                args = self._make_args(input=str(input_path), output_dir=tmp,
                                       run_id="test-run")
                self.assertEqual(el.run(args), 0)

                # 第二次无 --resume：应拒绝覆盖，返回 2
                self.assertEqual(el.run(args), 2)

                # 第三次 --resume：跳过已处理，不追加重复
                args2 = self._make_args(input=str(input_path), output_dir=tmp,
                                        run_id="test-run", resume=True)
                self.assertEqual(el.run(args2), 0)

            labeled = tmp_path / "achievements_labeled_v0.1-thin.jsonl"
            ids = [json.loads(l)["achievement_id"]
                   for l in labeled.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(ids, ["ach_1", "ach_2"])  # 无重复
            self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
