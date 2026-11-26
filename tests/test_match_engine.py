import argparse
import unittest
from unittest import mock

# 与实际实现对齐的导入：函数名一致，签名见各测试。
from scripts.match.b2_matcher import (
    B2_MODEL,
    B2_PROMPT_VERSION,
    match_demand,
    normalize_cosine,
)
from scripts.match.p1_rerank import _select_todo, rerank_one
from backend.tasks import MatchObjectNotFound, _run_match


def _vec() -> list[float]:
    return [0.1] * 1024


class TestB2Matcher(unittest.TestCase):

    def test_normalize_cosine(self):
        """余弦（约定 [0,1]）→ 0—100；越界 clamp。"""
        self.assertEqual(normalize_cosine(1.0), 100.0)
        self.assertEqual(normalize_cosine(0.5), 50.0)
        self.assertEqual(normalize_cosine(0.0), 0.0)
        self.assertEqual(normalize_cosine(-1.0), 0.0)  # 负数 clamp 到 0

    def test_match_id_format_and_hard_filter(self):
        """match_id 格式 + primary tech_field 硬过滤 + B2 来源字段非空。"""
        demand = {"demand_id": "dem_001", "tech_fields": ["cathode_material"], "required_trl": 5}
        # 成果 primary tech_field
        ach_primary = {
            "ach_001": {"code": "cathode_material", "confidence": 0.9},   # 匹配
            "ach_002": {"code": "anode_material", "confidence": 0.8},     # 应被硬过滤
        }
        ach_vectors = {"ach_001": _vec(), "ach_002": _vec()}
        ach_trl = {"ach_001": 3, "ach_002": 4}
        demand_vector = _vec()

        # match_demand(demand_dict, achievement_ids, ach_primary, ach_vectors, ach_trl, demand_vector, ...)
        results = match_demand(
            demand, ["ach_001", "ach_002"], ach_primary, ach_vectors, ach_trl, demand_vector,
            dataset_version="v0.1.2",
        )

        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["match_id"], "match_dem_001_ach_001")
        ach_ids = [r["achievement_id"] for r in results]
        self.assertNotIn("ach_002", ach_ids)  # 硬过滤：tech_field 对不上直接 pass
        self.assertIsNone(results[0]["risk"])
        self.assertIsNone(results[0]["evidence"])
        self.assertEqual(results[0]["model"], B2_MODEL)
        self.assertEqual(results[0]["prompt_version"], B2_PROMPT_VERSION)


class TestP1Rerank(unittest.TestCase):

    def _contexts(self):
        demand_ctx = {
            "demand_id": "dem_001",
            "title": "高镍正极需求",
            "pain_point": "现有正极循环衰减快。",
            "expected_solution": "开发单晶高镍正极。",
            "tech_fields": ["cathode_material"],
            "application_scenarios": ["ev_power"],
            "cooperation_modes": ["joint_rd"],
        }
        ach_ctx = {
            "achievement_id": "ach_001",
            "title_original": "高镍正极材料研究",
            "abstract_original": "本文研究高镍正极材料的循环稳定性。",
            "primary_tech_field": "cathode_material",
            "application_scenarios": ["ev_power"],
        }
        return demand_ctx, ach_ctx

    def _valid_result(self):
        return {
            "reason": "技术方向匹配，需关注中试放大。",
            "risk": {
                "technical": {"score": 3, "description": "需要中试验证。"},
                "market": {"score": 2, "description": "应用场景匹配。"},
                "ip": {"score": 3, "description": "论文未披露专利状态。"},
                "collaboration": {"score": 2, "description": "合作模式兼容。"},
                "overall": {"summary": "技术方向匹配。", "mitigation": ["先做中试", "做 IP 尽调"]},
            },
            "evidence": {
                "tag_matches": [{"dimension": "tech_field", "code": "cathode_material"}],
                "snippets": [{
                    "side": "achievement",
                    "field": "abstract_original",
                    "text": "高镍正极材料的循环稳定性",
                    "source_ref": "achievement.abstract_original",
                }],
                "metric_matches": [],
            },
        }

    def test_p1_success_and_alias_normalization(self):
        """P1 合法输出成功；achievement.abstract 别名归一化为真实字段。"""
        client = mock.Mock()
        result = self._valid_result()
        result["evidence"]["snippets"][0]["source_ref"] = "achievement.abstract"
        client.chat_json.return_value = result
        b2_match = {"match_id": "match_dem_001_ach_001", "risk": None, "evidence": None, "reason": "B2规则理由"}
        demand_ctx, ach_ctx = self._contexts()

        updated, ok = rerank_one(client, b2_match, demand_ctx, ach_ctx,
                                 model="qwen3.8-flash", prompt_version="v0.1")

        self.assertTrue(ok)
        self.assertEqual(updated["reason"], "技术方向匹配，需关注中试放大。")
        self.assertIsNotNone(updated["risk"])
        self.assertEqual(updated["evidence"]["snippets"][0]["source_ref"], "achievement.abstract_original")
        self.assertEqual(updated["evidence"]["snippets"][0]["field"], "abstract_original")

    def test_p1_fallback_on_api_error(self):
        """P1 API 报错时，返回 (原 match, ok=False)，不回抛。"""
        client = mock.Mock()
        client.chat_json.side_effect = Exception("API Timeout")
        b2_match = {"match_id": "match_dem_001_ach_001", "risk": None, "evidence": None, "reason": "B2规则理由"}
        demand_ctx, ach_ctx = self._contexts()

        updated, ok = rerank_one(client, b2_match, demand_ctx, ach_ctx,
                                 model="qwen3.8-flash", prompt_version="v0.1")

        self.assertFalse(ok)
        self.assertEqual(updated["reason"], "B2规则理由")
        self.assertIsNone(updated["risk"])
        self.assertIsNone(updated["evidence"])

    def test_p1_fallback_on_unquotable_snippet(self):
        """snippet 不是原文子串时必须回退 B2。"""
        client = mock.Mock()
        result = self._valid_result()
        result["evidence"]["snippets"][0]["text"] = "不存在的摘要"
        client.chat_json.return_value = result
        b2_match = {"match_id": "match_dem_001_ach_001", "risk": None, "evidence": None, "reason": "B2规则理由"}
        demand_ctx, ach_ctx = self._contexts()

        updated, ok = rerank_one(client, b2_match, demand_ctx, ach_ctx,
                                 model="qwen3.8-flash", prompt_version="v0.1")

        self.assertFalse(ok)
        self.assertIsNone(updated["evidence"])

    def test_p1_fallback_on_incomplete_risk(self):
        """risk 缺四维时不能当作成功。"""
        client = mock.Mock()
        result = self._valid_result()
        result["risk"].pop("market")
        client.chat_json.return_value = result
        b2_match = {"match_id": "match_dem_001_ach_001", "risk": None, "evidence": None, "reason": "B2规则理由"}
        demand_ctx, ach_ctx = self._contexts()

        updated, ok = rerank_one(client, b2_match, demand_ctx, ach_ctx,
                                 model="qwen3.8-flash", prompt_version="v0.1")

        self.assertFalse(ok)
        self.assertIsNone(updated["risk"])


class TestP1Selection(unittest.TestCase):

    def test_per_demand_selection_is_not_first_n(self):
        """--per-demand 1 应覆盖多个需求，而不是只取列表前 20 条。"""
        matches = [
            {"match_id": f"match_dem_{i:03d}_ach_001", "demand_id": f"dem_{i:03d}", "total_score": 90 - i}
            for i in range(1, 4)
        ]
        matches += [
            {"match_id": "match_dem_001_ach_002", "demand_id": "dem_001", "total_score": 80},
        ]
        args = argparse.Namespace(match_ids=None, per_demand=1, limit=3)
        selected = _select_todo(matches, args)
        self.assertEqual({m["demand_id"] for m in selected}, {"dem_001", "dem_002", "dem_003"})

    def test_match_ids_selection_requires_existing_id(self):
        matches = [{"match_id": "match_a", "demand_id": "dem_001", "total_score": 90}]
        args = argparse.Namespace(match_ids="match_missing", per_demand=None, limit=None)
        with self.assertRaises(ValueError):
            _select_todo(matches, args)


class TestCeleryTasks(unittest.TestCase):

    def test_task_idempotency(self):
        """幂等：已存在的 match_id 直接跳过，只插入新 match_id。"""
        matches = [
            {"match_id": "match_dem_001_ach_001", "achievement_id": "ach_001", "demand_id": "dem_001", "total_score": 80},
            {"match_id": "match_dem_001_ach_002", "achievement_id": "ach_002", "demand_id": "dem_001", "total_score": 70},
        ]
        # _run_match(object_type, object_id, run_id, version)
        with mock.patch("backend.tasks._set_status"), \
             mock.patch("backend.tasks._connect"), \
             mock.patch("backend.tasks._compute_b2_matches", return_value=matches), \
             mock.patch("backend.tasks._p1_rerank", return_value=False), \
             mock.patch("backend.tasks._existing_match_ids", return_value={"match_dem_001_ach_001"}), \
             mock.patch("backend.tasks._insert_match") as m_insert:
            result = _run_match("demand", "dem_001", "run_123", "v0.1.2")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["skipped"], 1)
        # 只插入 ach_002；ach_001 已存在被跳过
        self.assertEqual(m_insert.call_count, 1)
        self.assertEqual(m_insert.call_args[0][1]["match_id"], "match_dem_001_ach_002")

    def test_unknown_object_is_failed_not_success_zero(self):
        """未知发布对象必须失败，不能写成 success 0。"""
        with mock.patch("backend.tasks._set_status") as set_status, \
             mock.patch("backend.tasks._compute_b2_matches", side_effect=MatchObjectNotFound("missing")):
            with self.assertRaises(MatchObjectNotFound):
                _run_match("demand", "dem_missing", "run_missing", "v0.1.2")

        self.assertTrue(any(call.args[1] == "failed" for call in set_status.call_args_list))


if __name__ == "__main__":
    unittest.main()
