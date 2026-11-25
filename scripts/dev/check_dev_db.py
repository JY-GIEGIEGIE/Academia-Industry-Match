"""Check the v0.1.2 development database against the frozen acceptance counts."""

from __future__ import annotations

import argparse
import sys

import psycopg

try:  # direct script execution: python scripts/dev/check_dev_db.py
    from common import (
        DEFAULT_DB_NAME,
        EXPECTED_COUNTS,
        EXPECTED_NEEDS_REVIEW,
        EXPECTED_PRIMARY_TECH_FIELDS,
        EXPECTED_USERS,
        TAG_DIMENSION_COUNTS,
        dsn_for_db,
        load_env,
        redact_dsn,
    )
except ModuleNotFoundError:  # module execution: python -m scripts.dev.check_dev_db
    from .common import (
        DEFAULT_DB_NAME,
        EXPECTED_COUNTS,
        EXPECTED_NEEDS_REVIEW,
        EXPECTED_PRIMARY_TECH_FIELDS,
        EXPECTED_USERS,
        TAG_DIMENSION_COUNTS,
        dsn_for_db,
        load_env,
        redact_dsn,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--skip-users", action="store_true", help="run before seed_demo.py")
    args = parser.parse_args()

    dsn = args.dsn or dsn_for_db(args.db_name, load_env())
    print(f"target: {redact_dsn(dsn)}")
    failures: list[str] = []
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        def one(sql: str, params: tuple = ()) -> int:
            return int(conn.execute(sql, params).fetchone()[0])

        print("\ncounts")
        for table, expected in EXPECTED_COUNTS.items():
            actual = one(f"SELECT count(*) FROM {table}")
            ok = actual == expected
            print(f"  {table:24} {actual:>5} / {expected:<5} {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"{table}: {actual} != {expected}")

        print("\ntag breakdown")
        rows = dict(
            conn.execute(
                "SELECT dimension, count(*) FROM achievement_tag GROUP BY dimension"
            ).fetchall()
        )
        for dimension, expected in TAG_DIMENSION_COUNTS.items():
            actual = int(rows.get(dimension, 0))
            ok = actual == expected
            print(f"  {dimension:24} {actual:>5} / {expected:<5} {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"achievement_tag.{dimension}: {actual} != {expected}")

        checks = {
            "primary tech_field": (
                one("SELECT count(DISTINCT achievement_id) FROM achievement_tag "
                    "WHERE dimension = 'tech_field' AND is_primary"),
                EXPECTED_PRIMARY_TECH_FIELDS,
            ),
            "needs_review": (
                one("SELECT count(*) FROM achievement_extraction WHERE review_status = 'needs_review'"),
                EXPECTED_NEEDS_REVIEW,
            ),
            "embedding dim=1024": (
                one("SELECT count(*) FROM embedding WHERE dim = 1024"),
                EXPECTED_COUNTS["embedding"],
            ),
        }
        print("\nconsistency")
        for label, (actual, expected) in checks.items():
            ok = actual == expected
            print(f"  {label:24} {actual:>5} / {expected:<5} {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"{label}: {actual} != {expected}")

        has_users = bool(
            conn.execute("SELECT to_regclass('public.app_user') IS NOT NULL").fetchone()[0]
        )
        if not args.skip_users:
            users = one("SELECT count(*) FROM app_user") if has_users else 0
            note = "" if has_users else " (table missing)"
            print(f"  {'app_user':24} {users:>5} / {EXPECTED_USERS:<5} {'OK' if users == EXPECTED_USERS else 'FAIL'}{note}")
            if users != EXPECTED_USERS:
                failures.append(f"app_user: {users} != {EXPECTED_USERS}")

        has_intent = bool(
            conn.execute("SELECT to_regclass('public.intent') IS NOT NULL").fetchone()[0]
        )
        if has_intent:
            intents = one("SELECT count(*) FROM intent")
            print(f"  {'intent (informational)':24} {intents:>5}")
        else:
            print(f"  {'intent (informational)':24} {'n/a':>5} (table missing)")

    if failures:
        print("\nFAILED")
        for failure in failures:
            print("  -", failure)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
