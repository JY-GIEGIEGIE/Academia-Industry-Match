"""Unit tests for scripts/data/load_db.py (no database, no network)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "data"))

import load_db


def make_tag(code: str = "electrolyte", primary: bool = True, **overrides: object) -> dict:
    tag = {
        "dimension": "tech_field",
        "code": code,
        "is_primary": primary,
        "confidence": 0.9,
        "evidence": "sulfide electrolyte",
        "method": "llm",
        "review_status": "pending",
    }
    tag.update(overrides)
    return tag


class TaxonomyTests(unittest.TestCase):
    def test_loads_codes_by_dimension(self) -> None:
        codes = load_db.load_taxonomy_codes()
        self.assertEqual(len(codes["tech_field"]), 8)
        self.assertEqual(len(codes["application_scenario"]), 8)
        self.assertEqual(len(codes["cooperation_mode"]), 5)
        self.assertIn("electrolyte", codes["tech_field"])
        self.assertIn("ev_power", codes["application_scenario"])

    def test_missing_file_returns_empty(self) -> None:
        original = load_db.TAXONOMY_PATH
        try:
            load_db.TAXONOMY_PATH = PROJECT_ROOT / "data/spec/does_not_exist.md"
            self.assertEqual(load_db.load_taxonomy_codes(), {})
        finally:
            load_db.TAXONOMY_PATH = original


class ValidateLabeledTests(unittest.TestCase):
    def setUp(self) -> None:
        self.taxonomy = load_db.load_taxonomy_codes()
        self.ids = {"ach_1"}

    def check(self, rows: list[dict]) -> tuple[list[dict], load_db.Validation]:
        v = load_db.Validation()
        result = load_db.validate_labeled(rows, self.ids, self.taxonomy, v)
        return result, v

    def test_accepts_valid_record_and_builds_ids(self) -> None:
        rows, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(), make_tag(dimension="application_scenario", code="ev_power", primary=False)],
            "extraction": None,
        }])
        self.assertEqual(v.errors, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tags"][0]["tag_id"], "tag_ach_1_tech_field_electrolyte")
        self.assertEqual(rows[0]["tags"][1]["tag_id"], "tag_ach_1_application_scenario_ev_power")

    def test_rejects_code_outside_taxonomy(self) -> None:
        _, v = self.check([{"achievement_id": "ach_1", "tags": [make_tag(code="ev")], "extraction": None}])
        self.assertTrue(any("not in taxonomy" in error for error in v.errors))

    def test_requires_exactly_one_primary_tech_field(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(primary=False)],
            "extraction": None,
        }])
        self.assertTrue(any("expected exactly 1" in error for error in v.errors))

    def test_rejects_two_primary_tech_fields(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(), make_tag(code="separator")],
            "extraction": None,
        }])
        self.assertTrue(any("expected exactly 1" in error for error in v.errors))

    def test_primary_only_on_tech_field(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(), make_tag(dimension="application_scenario", code="ev_power", primary=True)],
            "extraction": None,
        }])
        self.assertTrue(any("only allowed on tech_field" in error for error in v.errors))

    def test_unknown_achievement_id(self) -> None:
        _, v = self.check([{"achievement_id": "ach_x", "tags": [], "extraction": None}])
        self.assertTrue(any("unknown achievement_id" in error for error in v.errors))

    def test_trl_requires_evidence(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag()],
            "extraction": {
                "trl": 4,
                "model": "qwen3.8-flash",
                "prompt_version": "v1",
                "ip_status": "unknown",
            },
        }])
        self.assertTrue(any("requires trl_evidence" in error for error in v.errors))

    def test_extraction_builds_id_and_keeps_run_id(self) -> None:
        rows, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag()],
            "extraction": {
                "trl": 4,
                "trl_evidence": "coin cell tested",
                "model": "qwen3.8-flash",
                "prompt_version": "v1",
                "ip_status": "unknown",
                "extraction_run_id": "extract-test",
            },
        }])
        self.assertEqual(v.errors, [])
        extraction = rows[0]["extraction"]
        self.assertIsNotNone(extraction)
        self.assertEqual(extraction["extraction_id"], "ext_ach_1")
        self.assertEqual(extraction["extraction_run_id"], "extract-test")

    def test_duplicate_achievement_id(self) -> None:
        record = {"achievement_id": "ach_1", "tags": [make_tag()], "extraction": None}
        _, v = self.check([record, dict(record)])
        self.assertTrue(any("duplicate achievement_id" in error for error in v.errors))

    def test_accepts_needs_review_on_tags_and_extractions(self) -> None:
        rows, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(review_status="needs_review")],
            "extraction": {
                "trl": None,
                "model": "qwen3.8-flash",
                "prompt_version": "v1",
                "ip_status": "unknown",
                "review_status": "needs_review",
            },
        }])
        self.assertEqual(v.errors, [])
        self.assertEqual(rows[0]["tags"][0]["review_status"], "needs_review")
        self.assertEqual(rows[0]["extraction"]["review_status"], "needs_review")

    def test_null_trl_and_empty_metrics_are_accepted(self) -> None:
        rows, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag()],
            "extraction": {
                "trl": None,
                "key_metrics": [],
                "process": [],
                "model": "qwen3.8-flash",
                "prompt_version": "v1",
                "ip_status": "unknown",
            },
        }])
        self.assertEqual(v.errors, [])
        self.assertIsNone(rows[0]["extraction"]["trl"])
        self.assertEqual(rows[0]["extraction"]["key_metrics"], [])

    def test_keeps_script_generated_tag_and_extraction_ids(self) -> None:
        rows, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(tag_id="tag_script_1")],
            "extraction": {
                "extraction_id": "ext_script_1",
                "trl": 4,
                "trl_evidence": "coin cell tested",
                "model": "qwen3.8-flash",
                "prompt_version": "v1",
                "ip_status": "unknown",
            },
        }])
        self.assertEqual(v.errors, [])
        self.assertEqual(rows[0]["tags"][0]["tag_id"], "tag_script_1")
        self.assertEqual(rows[0]["extraction"]["extraction_id"], "ext_script_1")

    def test_rejects_duplicate_script_tag_id(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [
                make_tag(tag_id="tag_dup"),
                make_tag(code="separator", primary=False, tag_id="tag_dup"),
            ],
            "extraction": None,
        }])
        self.assertTrue(any("duplicate tag_id" in error for error in v.errors))

    def test_tag_without_evidence_requires_needs_review(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(evidence="", confidence=0.3, review_status="pending")],
            "extraction": None,
        }])
        self.assertTrue(any("requires review_status=needs_review" in error for error in v.errors))

    def test_tag_without_evidence_needs_review_is_accepted(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(evidence="", confidence=0.3, review_status="needs_review")],
            "extraction": None,
        }])
        self.assertEqual(v.errors, [])

    def test_tag_without_evidence_rejects_high_confidence(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag(evidence=None, confidence=0.6, review_status="needs_review")],
            "extraction": None,
        }])
        self.assertTrue(any("contract requires <=0.4" in error for error in v.errors))

    def test_key_metrics_require_the_full_schema(self) -> None:
        _, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag()],
            "extraction": {
                "trl": 4,
                "trl_evidence": "coin cell tested",
                "key_metrics": [{"name": "ionic conductivity", "value": 10, "unit": "mS/cm"}],
                "model": "qwen3.8-flash",
                "prompt_version": "v1",
                "ip_status": "unknown",
            },
        }])
        self.assertTrue(any("evidence must be a non-empty string" in error for error in v.errors))

    def test_key_metrics_valid_schema_is_kept(self) -> None:
        rows, v = self.check([{
            "achievement_id": "ach_1",
            "tags": [make_tag()],
            "extraction": {
                "trl": 4,
                "trl_evidence": "coin cell tested",
                "key_metrics": [
                    {"name": "ionic conductivity", "value": 10, "unit": "mS/cm", "evidence": "10 mS cm-1"}
                ],
                "model": "qwen3.8-flash",
                "prompt_version": "v1",
                "ip_status": "unknown",
            },
        }])
        self.assertEqual(v.errors, [])
        self.assertEqual(len(rows[0]["extraction"]["key_metrics"]), 1)


class DatasetVersionTests(unittest.TestCase):
    def test_matching_version_passes(self) -> None:
        v = load_db.Validation()
        data = {
            "achievements": [{"dataset_version": "v0.1"}],
            "embeddings": [{"dataset_version": "v0.1"}],
            "enterprises": [{}],
        }
        load_db.check_dataset_versions(data, "v0.1", v)
        self.assertEqual(v.errors, [])

    def test_mismatch_is_an_error(self) -> None:
        v = load_db.Validation()
        data = {"embeddings": [{"dataset_version": "v0.1-thin"}]}
        load_db.check_dataset_versions(data, "v0.1", v)
        self.assertEqual(len(v.errors), 1)
        self.assertIn("v0.1-thin", v.errors[0])

    def test_blank_version_is_left_to_require(self) -> None:
        v = load_db.Validation()
        data = {"achievements": [{"dataset_version": "   "}]}
        load_db.check_dataset_versions(data, "v0.1", v)
        self.assertEqual(v.errors, [])

    def test_non_string_is_an_error(self) -> None:
        v = load_db.Validation()
        data = {"achievements": [{"dataset_version": 1}]}
        load_db.check_dataset_versions(data, "v0.1", v)
        self.assertEqual(len(v.errors), 1)
        self.assertIn("must be a string", v.errors[0])


class ValidateProfilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = {"ach_1"}

    def check(self, rows: list[dict]) -> tuple[list[dict], load_db.Validation]:
        v = load_db.Validation()
        return load_db.validate_profiles(rows, self.ids, v), v

    def test_builds_text_id_type_and_hash(self) -> None:
        text = "该成果围绕固态电池关键材料展开。" * 12
        rows, v = self.check([{"achievement_id": "ach_1", "language": "zh", "text": text}])
        self.assertEqual(v.errors, [])
        row = rows[0]
        self.assertEqual(row["text_id"], "txt_ach_1_capability_profile_zh_zh")
        self.assertEqual(row["text_type"], "capability_profile_zh")
        self.assertEqual(len(row["text_hash"]), 64)

    def test_english_uses_en_text_type(self) -> None:
        rows, _ = self.check([{"achievement_id": "ach_1", "language": "en", "text": "x" * 160}])
        self.assertEqual(rows[0]["text_type"], "capability_profile_en")

    def test_short_text_warns_but_passes(self) -> None:
        _rows, v = self.check([{"achievement_id": "ach_1", "language": "zh", "text": "太短"}])
        self.assertEqual(v.errors, [])
        self.assertTrue(any("below the 150-character" in warning for warning in v.warnings))

    def test_keeps_script_generated_text_id(self) -> None:
        rows, v = self.check([{
            "achievement_id": "ach_1",
            "language": "zh",
            "text": "该成果围绕固态电池关键材料展开。" * 12,
            "text_id": "txt_script_1",
        }])
        self.assertEqual(v.errors, [])
        self.assertEqual(rows[0]["text_id"], "txt_script_1")

    def test_rejects_duplicate_script_text_id(self) -> None:
        original = self.ids
        self.ids = {"ach_1", "ach_2"}
        try:
            _rows, v = self.check([
                {"achievement_id": "ach_1", "language": "zh", "text": "x" * 160, "text_id": "txt_dup"},
                {"achievement_id": "ach_2", "language": "zh", "text": "y" * 160, "text_id": "txt_dup"},
            ])
        finally:
            self.ids = original
        self.assertTrue(any("duplicate text_id" in error for error in v.errors))

    def test_empty_text_is_error(self) -> None:
        _, v = self.check([{"achievement_id": "ach_1", "language": "zh", "text": "   "}])
        self.assertTrue(any("empty text" in error for error in v.errors))

    def test_unknown_achievement_id(self) -> None:
        _, v = self.check([{"achievement_id": "ach_x", "language": "zh", "text": "x" * 160}])
        self.assertTrue(any("unknown achievement_id" in error for error in v.errors))


class HelperTests(unittest.TestCase):
    def test_redact_url_dsn(self) -> None:
        redacted = load_db.redact_dsn("postgresql://user:secret@127.0.0.1:5433/db")
        self.assertNotIn("secret", redacted)
        self.assertIn("***", redacted)

    def test_redact_keyword_dsn(self) -> None:
        redacted = load_db.redact_dsn("host=localhost password=secret dbname=db")
        self.assertNotIn("secret", redacted)

    def test_vector_value_formats_list(self) -> None:
        self.assertEqual(load_db.vector_value([0.5, 1]), "[0.5,1.0]")
        self.assertIsNone(load_db.vector_value(None))

    def test_build_csv_uses_null_marker(self) -> None:
        text = load_db.build_csv([{"a": None, "b": "x,y"}], ["a", "b"])
        self.assertEqual(text, "\\N,\"x,y\"\n")

    def test_build_rows_fills_dataset_version(self) -> None:
        rows = load_db.build_rows([{"a": "1"}], ["a", "dataset_version"], {}, "v0.1-thin")
        self.assertEqual(rows[0]["dataset_version"], "v0.1-thin")



class BlankVersionTests(unittest.TestCase):
    def test_blank_is_recognised(self) -> None:
        for value in (None, "", "   ", "\t"):
            self.assertTrue(load_db.is_blank(value), value)
        for value in ("v0.1", 0, []):
            self.assertFalse(load_db.is_blank(value), value)

    def test_build_rows_fills_blank_version(self) -> None:
        rows = load_db.build_rows(
            [{"dataset_version": "   "}, {"dataset_version": "v0.1-thin"}],
            ["dataset_version"],
            {},
            "v0.1",
        )
        self.assertEqual([row["dataset_version"] for row in rows], ["v0.1", "v0.1-thin"])


class DemandTagTests(unittest.TestCase):
    def test_derives_tags_with_one_primary_tech_field(self) -> None:
        rows = load_db.build_demand_tags([{
            "demand_id": "dem_1",
            "tech_fields": ["electrolyte", "separator"],
            "application_scenarios": ["ev_power"],
            "cooperation_modes": ["joint_rd"],
        }], "v0.1")
        self.assertEqual(len(rows), 4)
        tech = [row for row in rows if row["dimension"] == "tech_field"]
        self.assertEqual([row["is_primary"] for row in tech], [True, False])
        self.assertEqual(tech[0]["tag_id"], "tag_dem_1_tech_field_electrolyte")
        self.assertEqual(tech[0]["evidence"], "demand.tech_fields")
        self.assertEqual(tech[0]["method"], "rule")
        self.assertEqual(tech[0]["review_status"], "pending")

    def test_duplicate_demand_tag_codes_are_rejected(self) -> None:
        demand = {
            "demand_id": "dem_1", "enterprise_id": "ent_1", "title": "t",
            "pain_point": "p", "expected_solution": "e",
            "technical_metrics": [{"name": "x", "value": 1, "unit": "u"}],
            "cooperation_modes": ["joint_rd"], "required_trl": 5,
            "tech_fields": ["electrolyte", "electrolyte"],
            "application_scenarios": ["ev_power"], "region": "any",
            "status": "active", "valid_until": "2027-01-01",
            "is_simulated": True, "source_note": "team", "content_hash": "h",
            "dataset_version": "v0.1",
        }
        v = load_db.Validation()
        load_db.validate_demands([demand], {"ent_1"}, v)
        self.assertTrue(any("duplicate codes" in error for error in v.errors))


class CSVInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_query_csv_candidates_become_a_list(self) -> None:
        path = self.dir / "queries.csv"
        path.write_text(
            "query_id,query_text,query_language,query_type,target_tech_field,"
            "candidate_achievement_ids,relevant_achievement_ids,relevance_grades,annotator,notes\n"
            "q01,hello,zh,zh_business,electrolyte,a;b,,,,\n",
            encoding="utf-8-sig",
        )
        v = load_db.Validation()
        rows = load_db.load_table(path, "queries", True, v, csv_kind="queries")
        self.assertEqual(v.errors, [])
        self.assertEqual(rows[0]["candidate_achievement_ids"], ["a", "b"])

    def test_pair_csv_grade_becomes_int(self) -> None:
        path = self.dir / "pairs.csv"
        path.write_text(
            "pair_id,achievement_id,demand_id,relevance_grade,rationale,annotator,adjudication\n"
            "pair_001,ach_1,dem_1,2,ok,alice,\n",
            encoding="utf-8-sig",
        )
        v = load_db.Validation()
        rows = load_db.load_table(path, "pairs", True, v, csv_kind="pairs")
        self.assertEqual(v.errors, [])
        self.assertEqual(rows[0]["relevance_grade"], 2)

    def test_pair_csv_rejects_non_integer_grade(self) -> None:
        path = self.dir / "pairs.csv"
        path.write_text(
            "pair_id,achievement_id,demand_id,relevance_grade,rationale,annotator,adjudication\n"
            "pair_001,ach_1,dem_1,high,ok,alice,\n",
            encoding="utf-8-sig",
        )
        v = load_db.Validation()
        rows = load_db.load_table(path, "pairs", True, v, csv_kind="pairs")
        self.assertTrue(v.errors)
        self.assertIsNone(rows[0]["relevance_grade"])


class ResolvePathTests(unittest.TestCase):
    """Guard the switch between thin slice and full dataset files."""

    def make_args(self, version: str):
        import argparse

        return argparse.Namespace(
            dataset_version=version,
            achievements=None, labeled=None, profiles=None,
            embeddings=None, demands=None, enterprises=None,
            queries=None, pairs=None, manifest=None,
        )

    def test_thin_uses_thin_achievements_and_seed_seeds(self) -> None:
        args = self.make_args("v0.1-thin")
        load_db.resolve_data_paths(args)
        self.assertTrue(str(args.achievements).endswith("achievements_clean_v0.1-thin.jsonl"))
        self.assertTrue(str(args.demands).endswith("demands_seed_v0.1.jsonl"))
        self.assertTrue(str(args.enterprises).endswith("enterprises_seed_v0.1.jsonl"))
        self.assertTrue(str(args.queries).endswith("retrieval_queries_v0.1-thin.jsonl"))
        self.assertTrue(str(args.pairs).endswith("pair_labels_v0.1-thin.jsonl"))
        self.assertTrue(str(args.manifest).endswith("private_data_v0.1-thin.json"))

    def test_full_uses_processed_demands_and_enterprises(self) -> None:
        args = self.make_args("v0.1")
        load_db.resolve_data_paths(args)
        self.assertTrue(str(args.achievements).endswith("achievements_clean_v0.1.jsonl"))
        self.assertIn("processed", str(args.demands))
        self.assertTrue(str(args.demands).endswith("demands_v0.1.jsonl"))
        self.assertTrue(str(args.enterprises).endswith("enterprises_v0.1.jsonl"))
        self.assertTrue(str(args.queries).endswith("retrieval_queries_v0.1.jsonl"))
        self.assertTrue(str(args.pairs).endswith("pair_labels_v0.1.jsonl"))
        self.assertTrue(str(args.manifest).endswith("private_data_v0.1.json"))

    def test_explicit_path_is_not_overridden(self) -> None:
        args = self.make_args("v0.1")
        args.achievements = PROJECT_ROOT / "custom.jsonl"
        load_db.resolve_data_paths(args)
        self.assertEqual(args.achievements, PROJECT_ROOT / "custom.jsonl")


if __name__ == "__main__":
    unittest.main()
