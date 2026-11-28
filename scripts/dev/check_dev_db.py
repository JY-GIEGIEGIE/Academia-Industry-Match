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
    parser.add_argument("--require-binding", action="store_true",
                        help="require one bound achievement and one bound demand")
    parser.add_argument("--expect-achievement-id", default=None,
                        help="also require this achievement to be bound to user_research_demo")
    parser.add_argument("--expect-demand-id", default=None,
                        help="also require this demand to be bound to user_enterprise_demo")
    parser.add_argument("--require-dispatch", action="store_true",
                        help="require the match_dispatch table and its expected columns")
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

        has_dispatch = bool(
            conn.execute("SELECT to_regclass('public.match_dispatch') IS NOT NULL").fetchone()[0]
        )
        required_dispatch_cols = {
            "run_id", "object_type", "object_id", "publisher_user_id",
            "dispatch_status", "attempt_count", "last_error",
            "claimed_at", "submitted_at", "created_at", "updated_at",
        }
        if has_dispatch:
            dispatch_cols = {
                row[0] for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'match_dispatch'"
                ).fetchall()
            }
            missing_cols = sorted(required_dispatch_cols - dispatch_cols)
            dispatch_count = one("SELECT count(*) FROM match_dispatch")
            note = "" if not missing_cols else f" (missing: {', '.join(missing_cols)})"
            print(f"  {'match_dispatch':24} {dispatch_count:>5}{note}")
            if args.require_dispatch and missing_cols:
                failures.append(
                    f"match_dispatch: missing columns {', '.join(missing_cols)}"
                )
        else:
            print(f"  {'match_dispatch':24} {'n/a':>5} (table missing)")
            if args.require_dispatch:
                failures.append("match_dispatch: table missing")

        has_publisher_a = bool(
            conn.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'achievement' AND column_name = 'publisher_user_id'"
            ).fetchone()[0]
        )
        has_publisher_d = bool(
            conn.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'demand' AND column_name = 'publisher_user_id'"
            ).fetchone()[0]
        )
        has_binding = has_users and has_publisher_a and has_publisher_d
        if has_binding:
            bound_a = one(
                "SELECT count(*) FROM achievement "
                "WHERE publisher_user_id = 'user_research_demo'"
            )
            bound_d = one(
                "SELECT count(*) FROM demand "
                "WHERE publisher_user_id = 'user_enterprise_demo'"
            )
            valid_a = one(
                "SELECT count(*) FROM achievement a "
                "JOIN app_user u ON u.user_id = a.publisher_user_id "
                "WHERE a.publisher_user_id = 'user_research_demo' "
                "AND a.published_at IS NOT NULL AND u.role = 'researcher'"
            )
            valid_d = one(
                "SELECT count(*) FROM demand d "
                "JOIN app_user u ON u.user_id = d.publisher_user_id "
                "WHERE d.publisher_user_id = 'user_enterprise_demo' "
                "AND d.published_at IS NOT NULL AND u.role = 'enterprise'"
            )
            print(f"  {'bound achievement':24} {bound_a:>5} / {1:<5} "
                  f"{'OK' if bound_a == 1 else 'WARN'}")
            print(f"  {'bound demand':24} {bound_d:>5} / {1:<5} "
                  f"{'OK' if bound_d == 1 else 'WARN'}")
            print(f"  {'valid researcher bind':24} {valid_a:>5} / {1:<5} "
                  f"{'OK' if valid_a == 1 else 'WARN'}")
            print(f"  {'valid enterprise bind':24} {valid_d:>5} / {1:<5} "
                  f"{'OK' if valid_d == 1 else 'WARN'}")
            actual_a = conn.execute(
                "SELECT achievement_id, publisher_user_id FROM achievement "
                "WHERE publisher_user_id IS NOT NULL ORDER BY 1"
            ).fetchall()
            actual_d = conn.execute(
                "SELECT demand_id, publisher_user_id FROM demand "
                "WHERE publisher_user_id IS NOT NULL ORDER BY 1"
            ).fetchall()
            print(f"  {'bound ids':24} achievement={actual_a} demand={actual_d}")
            if args.expect_achievement_id:
                expected_a = one(
                    "SELECT count(*) FROM achievement "
                    "WHERE achievement_id = %s AND publisher_user_id = 'user_research_demo' "
                    "AND published_at IS NOT NULL",
                    (args.expect_achievement_id,),
                )
                print(f"  {'expected achievement':24} {expected_a:>5} / {1:<5} "
                      f"{'OK' if expected_a == 1 else 'FAIL'}")
                if expected_a != 1:
                    failures.append(
                        f"expected achievement binding missing: {args.expect_achievement_id}"
                    )
            if args.expect_demand_id:
                expected_d = one(
                    "SELECT count(*) FROM demand "
                    "WHERE demand_id = %s AND publisher_user_id = 'user_enterprise_demo' "
                    "AND published_at IS NOT NULL",
                    (args.expect_demand_id,),
                )
                print(f"  {'expected demand':24} {expected_d:>5} / {1:<5} "
                      f"{'OK' if expected_d == 1 else 'FAIL'}")
                if expected_d != 1:
                    failures.append(
                        f"expected demand binding missing: {args.expect_demand_id}"
                    )
            if args.require_binding and (
                bound_a != 1 or bound_d != 1 or valid_a != 1 or valid_d != 1
            ):
                failures.append(
                    "demo binding: "
                    f"achievement={bound_a}/{valid_a}, demand={bound_d}/{valid_d}, expected 1/1"
                )
        else:
            print(f"  {'demo binding':24} {'n/a':>5} (app_user/publisher columns missing)")
            if args.require_binding or args.expect_achievement_id or args.expect_demand_id:
                failures.append("demo binding: app_user or publisher columns missing")

    if failures:
        print("\nFAILED")
        for failure in failures:
            print("  -", failure)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
