#!/usr/bin/env python3
"""API container healthcheck: hit /health, which also checks PostgreSQL."""

from __future__ import annotations

import sys
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
            response.read()
    except Exception as exc:  # noqa: BLE001 - healthcheck must turn any error into exit 1
        print(f"api healthcheck failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
