"""Create the v0.1.2 development database used by the second sprint."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

try:  # direct script execution: python scripts/dev/create_dev_db.py
    from common import (
        DEFAULT_DB_NAME,
        EMBEDDING_MODEL_VERSION,
        PROJECT_ROOT,
        dsn_for_db,
        dsn_target,
        ensure_dev_db,
        load_env,
        redact_dsn,
    )
except ModuleNotFoundError:  # module execution: python -m scripts.dev.create_dev_db
    from .common import (
        DEFAULT_DB_NAME,
        EMBEDDING_MODEL_VERSION,
        PROJECT_ROOT,
        dsn_for_db,
        dsn_target,
        ensure_dev_db,
        load_env,
        redact_dsn,
    )

PROCESSED = PROJECT_ROOT / "data" / "processed"
EVAL = PROJECT_ROOT / "data" / "eval"


def data_paths() -> dict[str, Path]:
    paths = {
        "achievements": PROCESSED / "achievements_clean_v0.1.2.jsonl",
        "demands": PROCESSED / "demands_v0.1.2.jsonl",
        "enterprises": PROCESSED / "enterprises_v0.1.2.jsonl",
        "labeled": PROCESSED / "achievements_labeled_v0.1.2.jsonl",
        "profiles": PROCESSED / "capability_profiles_v0.1.2.jsonl",
        "embeddings": PROCESSED / "embeddings_v0.1.2.jsonl",
        "queries": EVAL / "retrieval_queries_v0.1.2.jsonl",
        "pairs": EVAL / "pair_labels_v0.1.2.jsonl",
        "manifest": PROJECT_ROOT / "data" / "manifests" / "private_data_v0.1.2.json",
        "dataset_manifest": PROJECT_ROOT / "data" / "manifests" / "dataset_v0.1.2.json",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise SystemExit(
            "缺少 v0.1.2 文件：\n  " + "\n  ".join(missing)
            + "\n请先从 S-08_v0.1.2_2026-11-23.zip 解压到 data/processed 与 data/eval。"
        )
    return paths


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def preflight_hashes(paths: dict[str, Path], zip_path: Path | None) -> dict:
    """Verify every manifest file and the optional handoff zip before creating the DB."""
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    checked: set[Path] = set()
    for manifest_key in ("manifest", "dataset_manifest"):
        manifest_path = paths.get(manifest_key)
        if manifest_path is None or not manifest_path.exists():
            continue
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = data.get("files", [])
        if isinstance(entries, dict):
            entries = list(entries.values())
        for entry in entries:
            path = Path(entry["path"])
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if path in checked:
                continue
            checked.add(path)
            if not path.exists():
                raise SystemExit(f"manifest file missing: {path}")
            if sha256_file(path) != entry.get("sha256"):
                raise SystemExit(f"hash mismatch: {path}")
    package = manifest.get("package") or {}
    if zip_path is not None:
        if not zip_path.is_file():
            raise SystemExit(f"--zip is not a file: {zip_path}")
        if package.get("sha256") and sha256_file(zip_path) != package["sha256"]:
            raise SystemExit(f"hash mismatch: {zip_path}")
        if not package.get("sha256"):
            print(
                "warning: manifest has no package.sha256; "
                "skipping zip-level check (file hashes were still verified)",
                flush=True,
            )
    return manifest


def create_database(dsn: str, db_name: str, recreate: bool, allow_non_dev: bool = False) -> None:
    import psycopg  # lazy import: tests can import this module without DB deps

    if recreate and not allow_non_dev and not db_name.startswith("s2_mvp_"):
        raise SystemExit(
            f"refusing to drop non-development database: {db_name} "
            "(only s2_mvp_* may be recreated)"
        )
    target = dsn_target(dsn)
    admin = psycopg.connect(
        host=target["host"],
        port=target["port"],
        user=target["user"],
        password=target["password"],
        dbname="postgres",
        connect_timeout=10,
        autocommit=True,
    )
    try:
        exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        ).fetchone()
        if exists and recreate:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            admin.execute(f'DROP DATABASE "{db_name}"')
            print(f"dropped existing database: {db_name}")
            exists = None
        if exists:
            print(f"database already exists, reusing: {db_name}")
        else:
            admin.execute(f'CREATE DATABASE "{db_name}"')
            print(f"created database: {db_name}")
    finally:
        admin.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-name", default=None, help=f"default: {DEFAULT_DB_NAME}")
    parser.add_argument("--dsn", default=None, help="full DSN override; database name is read from it")
    parser.add_argument("--recreate", action="store_true", help="drop and recreate the target database")
    parser.add_argument("--skip-load", action="store_true", help="only create the database")
    parser.add_argument("--allow-non-dev", action="store_true", help="allow a database outside s2_mvp_*")
    parser.add_argument("--zip", type=Path, default=None, help="optional handoff zip for hash verification")
    args = parser.parse_args()

    dsn = args.dsn or dsn_for_db(args.db_name or DEFAULT_DB_NAME, load_env())
    db_name = str(dsn_target(dsn)["dbname"])
    if args.db_name and args.db_name != db_name:
        raise SystemExit(
            f"--db-name {args.db_name!r} does not match the database in --dsn ({db_name!r})"
        )
    ensure_dev_db(db_name, args.allow_non_dev)
    print(f"target: {redact_dsn(dsn)}", flush=True)
    paths = None if args.skip_load else data_paths()
    manifest = preflight_hashes(paths, args.zip) if paths else None
    create_database(dsn, db_name, args.recreate, args.allow_non_dev)
    if args.skip_load:
        return 0

    assert paths is not None and manifest is not None
    embedding_model = manifest.get("embedding_model_version") or EMBEDDING_MODEL_VERSION
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "data" / "load_db.py"),
        "--dsn",
        dsn,
        "--migrate",
        "--dataset-version",
        "v0.1.2",
        "--embedding-model-version",
        embedding_model,
        "--achievements",
        str(paths["achievements"]),
        "--demands",
        str(paths["demands"]),
        "--enterprises",
        str(paths["enterprises"]),
        "--labeled",
        str(paths["labeled"]),
        "--profiles",
        str(paths["profiles"]),
        "--embeddings",
        str(paths["embeddings"]),
        "--queries",
        str(paths["queries"]),
        "--pairs",
        str(paths["pairs"]),
        "--manifest",
        str(paths["manifest"]),
        "--report",
        str(PROJECT_ROOT / "data" / "manifests" / "load_report_v0.1.2_dev.md"),
        "--import-manifest",
        str(PROJECT_ROOT / "data" / "manifests" / "import_v0.1.2_dev.json"),
    ]
    package_sha = (manifest.get("package") or {}).get("sha256")
    if args.zip and package_sha:
        command.extend(["--zip", str(args.zip)])
    print("loading v0.1.2 into the development database ...", flush=True)
    result = subprocess.run(command, check=False, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        return result.returncode
    print("\n下一步：")
    print(f"  {sys.executable} scripts/dev/seed_demo.py --db-name {db_name}")
    print(f"  {sys.executable} scripts/dev/check_dev_db.py --db-name {db_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
