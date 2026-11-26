import unittest
from unittest import mock

# 与实际实现对齐的导入：函数名一致，签名见各测试。
from scripts.match.b2_matcher import normalize_cosine, match_demand
from scripts.match.p1_rerank import rerank_one
from backend.tasks import _run_match


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
        """match_id 格式 + primary tech_field 硬过滤 + risk/evidence 为 null。"""
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


class TestP1Rerank(unittest.TestCase):

    def test_p1_success(self):
        """P1 正常调用大模型，返回 (match, ok=True)。"""
        client = mock.Mock()
        client.chat_json.return_value = {
            "reason": "大模型生成的理由",
            "risk": {"technical": {"score": 4, "description": "..."}},
            "evidence": {"tag_matches": []},
        }
        b2_match = {"match_id": "match_dem_001_ach_001", "risk": None, "evidence": None, "reason": "B2规则理由"}
        demand_ctx = {"demand_id": "dem_001"}
        ach_ctx = {"achievement_id": "ach_001"}

        updated, ok = rerank_one(client, b2_match, demand_ctx, ach_ctx,
                                 model="qwen3.8-flash", prompt_version="v0.1")

        self.assertTrue(ok)
        self.assertEqual(updated["reason"], "大模型生成的理由")
        self.assertIsNotNone(updated["risk"])
        self.assertIsNotNone(updated["evidence"])

    def test_p1_fallback_on_api_error(self):
        """P1 API 报错时，返回 (原 match, ok=False)，不回抛。"""
        client = mock.Mock()
        client.chat_json.side_effect = Exception("API Timeout")
        b2_match = {"match_id": "match_dem_001_ach_001", "risk": None, "evidence": None, "reason": "B2规则理由"}
        demand_ctx = {"demand_id": "dem_001"}
        ach_ctx = {"achievement_id": "ach_001"}

        updated, ok = rerank_one(client, b2_match, demand_ctx, ach_ctx,
                                 model="qwen3.8-flash", prompt_version="v0.1")

        self.assertFalse(ok)
        self.assertEqual(updated["reason"], "B2规则理由")
        self.assertIsNone(updated["risk"])
        self.assertIsNone(updated["evidence"])


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


if __name__ == "__main__":
    unittest.main()
