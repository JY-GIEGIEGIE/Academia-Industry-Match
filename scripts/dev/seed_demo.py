"""Seed the two demonstration accounts and optionally bind demo records."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime

import psycopg

try:  # direct script execution: python scripts/dev/seed_demo.py
    from common import (
        DEFAULT_DB_NAME,
        dsn_for_db,
        dsn_target,
        ensure_dev_db,
        hash_password,
        load_env,
        redact_dsn,
    )
except ModuleNotFoundError:  # module execution: python -m scripts.dev.seed_demo
    from .common import (
        DEFAULT_DB_NAME,
        dsn_for_db,
        dsn_target,
        ensure_dev_db,
        hash_password,
        load_env,
        redact_dsn,
    )

ACCOUNTS = (
    {
        "user_id": "user_research_demo",
        "username": "research_demo",
        "role": "researcher",
        "display_name": "科研演示用户",
    },
    {
        "user_id": "user_enterprise_demo",
        "username": "enterprise_demo",
        "role": "enterprise",
        "display_name": "企业演示用户",
    },
)


def upsert_account(conn: psycopg.Connection, account: dict[str, str], password: str, reset: bool) -> None:
    conflict = conn.execute(
        "SELECT user_id FROM app_user WHERE username = %s AND user_id <> %s",
        (account["username"], account["user_id"]),
    ).fetchone()
    if conflict:
        raise SystemExit(
            f"username {account['username']!r} already belongs to {conflict[0]!r}; "
            "refusing to create a duplicate demo account"
        )
    existing = conn.execute(
        "SELECT password_hash FROM app_user WHERE user_id = %s",
        (account["user_id"],),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO app_user (user_id, username, password_hash, role, display_name) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                account["user_id"],
                account["username"],
                hash_password(password),
                account["role"],
                account["display_name"],
            ),
        )
        print(f"created account: {account['username']} ({account['role']})")
        return
    if reset:
        conn.execute(
            "UPDATE app_user SET password_hash = %s WHERE user_id = %s",
            (hash_password(password), account["user_id"]),
        )
    conn.execute(
        "UPDATE app_user SET username = %s, role = %s, display_name = %s WHERE user_id = %s",
        (account["username"], account["role"], account["display_name"], account["user_id"]),
    )
    print(f"updated account: {account['username']} ({account['role']})")


def bind_record(
    conn: psycopg.Connection,
    table: str,
    id_column: str,
    record_id: str,
    user_id: str,
    published_at: datetime,
) -> None:
    row = conn.execute(
        f"SELECT publisher_user_id FROM {table} WHERE {id_column} = %s",
        (record_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"{table}: record not found: {record_id}")
    # Demo accounts own exactly one record: clear a previous binding first so
    # rebinding to S-13's final IDs does not leave two demo rows behind.
    conn.execute(
        f"UPDATE {table} SET publisher_user_id = NULL, published_at = NULL "
        f"WHERE publisher_user_id = %s AND {id_column} <> %s",
        (user_id, record_id),
    )
    conn.execute(
        f"UPDATE {table} SET publisher_user_id = %s, "
        f"published_at = COALESCE(published_at, %s) WHERE {id_column} = %s",
        (user_id, published_at, record_id),
    )
    print(f"bound {table}.{id_column}={record_id} -> {user_id}")


def unbind_record(conn: psycopg.Connection, table: str, id_column: str, record_id: str) -> None:
    cursor = conn.execute(
        f"UPDATE {table} SET publisher_user_id = NULL, published_at = NULL "
        f"WHERE {id_column} = %s",
        (record_id,),
    )
    if cursor.rowcount == 0:
        raise SystemExit(f"{table}: record not found: {record_id}")
    print(f"unbound {table}.{id_column}={record_id}")


def main() -> int:
    env = load_env()
    default_password = os.environ.get("DEMO_PASSWORD") or env.get("DEMO_PASSWORD") or "demo1234"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--password", default=default_password)
    parser.add_argument("--reset-password", action="store_true", help="rewrite the hash on existing accounts")
    parser.add_argument("--achievement-id", default=None, help="demo achievement to bind to research_demo")
    parser.add_argument("--demand-id", default=None, help="demo demand to bind to enterprise_demo")
    parser.add_argument("--unbind", action="store_true", help="clear publisher fields for the given demo ids")
    parser.add_argument("--allow-non-dev", action="store_true", help="allow a database outside s2_mvp_*")
    args = parser.parse_args()
    if args.unbind and not (args.achievement_id or args.demand_id):
        parser.error("--unbind requires --achievement-id and/or --demand-id")

    dsn = args.dsn or dsn_for_db(args.db_name, env)
    ensure_dev_db(str(dsn_target(dsn)["dbname"]), args.allow_non_dev)
    print(f"target: {redact_dsn(dsn)}")
    published_at = datetime.now(UTC)
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        for account in ACCOUNTS:
            upsert_account(conn, account, args.password, args.reset_password)
        if args.achievement_id:
            if args.unbind:
                unbind_record(conn, "achievement", "achievement_id", args.achievement_id)
            else:
                bind_record(conn, "achievement", "achievement_id", args.achievement_id,
                            "user_research_demo", published_at)
        else:
            print("skip achievement binding: --achievement-id not provided (waiting for S-13)")
        if args.demand_id:
            if args.unbind:
                unbind_record(conn, "demand", "demand_id", args.demand_id)
            else:
                bind_record(conn, "demand", "demand_id", args.demand_id,
                            "user_enterprise_demo", published_at)
        else:
            print("skip demand binding: --demand-id not provided (waiting for S-13)")
        users = conn.execute("SELECT count(*) FROM app_user").fetchone()[0]
        bound_a = conn.execute(
            "SELECT count(*) FROM achievement WHERE publisher_user_id IS NOT NULL"
        ).fetchone()[0]
        bound_d = conn.execute(
            "SELECT count(*) FROM demand WHERE publisher_user_id IS NOT NULL"
        ).fetchone()[0]
    print(f"app_user={users}, bound achievement={bound_a}, bound demand={bound_d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
