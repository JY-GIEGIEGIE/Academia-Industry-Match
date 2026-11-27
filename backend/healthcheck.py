#!/usr/bin/env python3
"""Worker healthcheck: the database is reachable and points at s2_mvp_*."""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

import psycopg


def main() -> int:
    dsn = os.environ.get("DATABASE_URL", "")
    database = urlparse(dsn).path.lstrip("/")
    if not database.startswith("s2_mvp_"):
        print(f"unexpected database: {database or '<empty>'}", file=sys.stderr)
        return 1
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except Exception as exc:  # noqa: BLE001 - healthcheck must turn any error into exit 1
        print(f"database healthcheck failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
