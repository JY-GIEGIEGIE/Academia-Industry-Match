"""Unit tests for the S-12 development-database helpers (no database)."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "dev"))

import common
import create_dev_db


class PasswordHashTests(unittest.TestCase):
    def test_hash_format_and_verify(self) -> None:
        stored = common.hash_password("demo1234", salt_hex="00" * 16, iterations=1000)
        self.assertEqual(stored.count("$"), 3)
        self.assertTrue(stored.startswith("pbkdf2_sha256$1000$"))
        self.assertTrue(common.verify_password("demo1234", stored))
        self.assertFalse(common.verify_password("wrong", stored))

    def test_hash_uses_random_salt(self) -> None:
        first = common.hash_password("demo1234")
        second = common.hash_password("demo1234")
        self.assertNotEqual(first, second)
        self.assertTrue(common.verify_password("demo1234", first))
        self.assertTrue(common.verify_password("demo1234", second))

    def test_malformed_hash_is_rejected(self) -> None:
        for value in ("", "plain", "md5$1$aa$bb", "pbkdf2_sha256$x$aa$bb"):
            with self.subTest(value=value):
                self.assertFalse(common.verify_password("demo1234", value))

    def test_empty_password_rejected(self) -> None:
        with self.assertRaises(ValueError):
            common.hash_password("")


class DsnTests(unittest.TestCase):
    def test_dsn_for_db_keeps_credentials_and_query(self) -> None:
        env = {
            "DATABASE_URL": "postgresql://aim:secret@127.0.0.1:5433/academia_industry_match?sslmode=disable"
        }
        dsn = common.dsn_for_db("s2_mvp_20261125", env)
        self.assertIn("s2_mvp_20261125", dsn)
        self.assertNotIn("academia_industry_match", dsn)
        self.assertIn("aim:secret", dsn)
        self.assertIn("sslmode=disable", dsn)

    def test_redact_dsn_hides_password(self) -> None:
        dsn = "postgresql://aim:secret@127.0.0.1:5433/db"
        self.assertNotIn("secret", common.redact_dsn(dsn))
        self.assertIn("aim:***@", common.redact_dsn(dsn))


class ExpectedCountTests(unittest.TestCase):
    def test_tag_dimensions_sum_to_total(self) -> None:
        self.assertEqual(sum(common.TAG_DIMENSION_COUNTS.values()), common.EXPECTED_COUNTS["achievement_tag"])

    def test_expected_counts_present(self) -> None:
        for key in ("achievement", "embedding", "demand_tag", "eval_query", "eval_label"):
            self.assertIn(key, common.EXPECTED_COUNTS)


class DevDbGuardTests(unittest.TestCase):
    def test_non_dev_database_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            common.ensure_dev_db("academia_industry_match")

    def test_dev_database_is_allowed(self) -> None:
        self.assertIsNone(common.ensure_dev_db("s2_mvp_20261125"))

    def test_explicit_override(self) -> None:
        self.assertIsNone(common.ensure_dev_db("academia_industry_match", allow_non_dev=True))


class PreflightTests(unittest.TestCase):
    def _paths(self, root: Path, digest: str) -> dict[str, Path]:
        data_file = root / "data.jsonl"
        data_file.write_text("{}\n", encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps({"files": [{"path": str(data_file), "sha256": digest}]}),
            encoding="utf-8",
        )
        return {"manifest": manifest}

    def test_valid_hash_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_file = root / "data.jsonl"
            data_file.write_text("{}\n", encoding="utf-8")
            digest = hashlib.sha256(data_file.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({"files": [{"path": str(data_file), "sha256": digest}]}),
                encoding="utf-8",
            )
            result = create_dev_db.preflight_hashes({"manifest": manifest}, None)
            self.assertIn("files", result)

    def test_bad_hash_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root, "0" * 64)
            with self.assertRaises(SystemExit):
                create_dev_db.preflight_hashes(paths, None)

    def test_missing_zip_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_file = root / "data.jsonl"
            data_file.write_text("{}\n", encoding="utf-8")
            digest = hashlib.sha256(data_file.read_bytes()).hexdigest()
            paths = self._paths(root, digest)
            with self.assertRaises(SystemExit):
                create_dev_db.preflight_hashes(paths, root / "missing.zip")


if __name__ == "__main__":
    unittest.main()
