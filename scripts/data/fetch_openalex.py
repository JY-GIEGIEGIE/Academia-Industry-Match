#!/usr/bin/env python3
"""Fetch OpenAlex works for the thin-slice dataset.

Design goals:
- keep raw API responses immutable under data/raw/openalex/<run_id>/
- make every run reproducible via a manifest in data/manifests/
- be polite: one request at a time, retry with backoff, optional mailto/key
- do not depend on third-party packages

Usage:
    python scripts/data/fetch_openalex.py --run-id thin-20261117 --per-page 100
    python scripts/data/fetch_openalex.py --tags electrolyte,cathode --lenses relevance
    python scripts/data/fetch_openalex.py --dry-run

Environment:
    OPENALEX_MAILTO    optional; recommended for the polite pool
    OPENALEX_API_KEY   optional; free key gives a larger daily budget
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from config import (
    MANIFEST_DIR,
    OPENALEX_API,
    OPENALEX_SELECT,
    RAW_DIR,
    SUBFIELD_SPECS,
    YEAR_FROM,
    YEAR_TO,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(value: str, limit: int = 40) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return value[:limit] or "query"


def build_url(
    query: str,
    lens: str,
    per_page: int,
    mailto: str | None,
    api_key: str | None,
) -> str:
    filters = [
        f'title_and_abstract.search:"{query}"',
        f"publication_year:{YEAR_FROM}-{YEAR_TO}",
        "has_abstract:true",
        "type:article|review",
    ]
    params = {
        "filter": ",".join(filters),
        "per-page": str(per_page),
        "cursor": "*",
        "select": OPENALEX_SELECT,
    }
    if lens == "recent":
        params["sort"] = "publication_date:desc"
    elif lens == "cited":
        params["sort"] = "cited_by_count:desc"
    # "relevance" is OpenAlex's default order; no sort parameter is needed.
    if mailto:
        params["mailto"] = mailto
    if api_key:
        params["api_key"] = api_key
    return f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"


def fetch_json(url: str, mailto: str | None, retries: int = 3, timeout: int = 90) -> dict:
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "academia-industry-match/0.1 "
            f"(mailto:{mailto})" if mailto else "academia-industry-match/0.1"
        ),
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                return {
                    "status": response.status,
                    "payload": json.loads(body.decode("utf-8")),
                }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code}: {body[:500]}")
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise last_error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"failed after {retries} attempts: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch OpenAlex works for the thin slice.")
    parser.add_argument(
        "--run-id",
        default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        help="Run identifier; raw snapshots go under data/raw/openalex/<run-id>/.",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=100,
        help="OpenAlex per-page size (max 200). One page is enough for the thin slice.",
    )
    parser.add_argument(
        "--lenses",
        default="relevance,recent",
        help="Comma-separated views: relevance, recent, cited.",
    )
    parser.add_argument(
        "--tags",
        default=",".join(SUBFIELD_SPECS.keys()),
        help="Comma-separated subfield tags; default: all.",
    )
    parser.add_argument(
        "--mailto",
        default=os.environ.get("OPENALEX_MAILTO"),
        help="Email for OpenAlex polite pool (or set OPENALEX_MAILTO).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENALEX_API_KEY"),
        help="OpenAlex API key (or set OPENALEX_API_KEY).",
    )
    parser.add_argument("--force", action="store_true", help="Re-fetch existing raw files.")
    parser.add_argument("--dry-run", action="store_true", help="Print URLs without fetching.")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args()
    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    lenses = [lens.strip() for lens in args.lenses.split(",") if lens.strip()]
    unknown_tags = [tag for tag in tags if tag not in SUBFIELD_SPECS]
    if unknown_tags:
        print(f"Unknown tags: {unknown_tags}", file=sys.stderr)
        return 2

    run_dir = RAW_DIR / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    files: list[dict] = []
    errors: list[str] = []
    total_returned = 0
    total_cost = 0.0

    for tag in tags:
        spec = SUBFIELD_SPECS[tag]
        for query in spec["queries"]:
            for lens in lenses:
                filename = f"{tag}__{lens}__{slugify(query)}.json"
                target = run_dir / filename
                relative = target.relative_to(Path(__file__).resolve().parents[2])
                record = {
                    "tag": tag,
                    "tech_field": spec["tech_field"],
                    "query": query,
                    "lens": lens,
                    "path": str(relative),
                }
                if target.exists() and not args.force:
                    record.update({"status": "skipped", "returned": 0})
                    files.append(record)
                    print(f"[skip] {tag} / {lens}: {relative}")
                    continue

                url = build_url(query, lens, args.per_page, args.mailto, args.api_key)
                if args.dry_run:
                    record.update({"status": "dry_run", "returned": 0, "url": url})
                    files.append(record)
                    print(url)
                    continue

                print(f"[fetch] {tag} / {lens}: {query}")
                try:
                    result = fetch_json(url, args.mailto)
                except Exception as exc:  # noqa: BLE001 - report and continue
                    message = f"{tag}/{lens}/{query}: {exc}"
                    errors.append(message)
                    record.update({"status": "failed", "error": str(exc), "returned": 0})
                    files.append(record)
                    print(f"  ! {message}", file=sys.stderr)
                    continue

                payload = result["payload"]
                target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
                meta = payload.get("meta", {})
                count = int(meta.get("count") or 0)
                returned = len(payload.get("results", []))
                cost = float(meta.get("cost_usd") or 0.0)
                total_returned += returned
                total_cost += cost
                record.update(
                    {
                        "status": "ok",
                        "http_status": result["status"],
                        "count": count,
                        "returned": returned,
                        "cost_usd": cost,
                    }
                )
                files.append(record)
                print(f"  -> {returned} records, count={count}, cost=${cost:.4f}")
                time.sleep(0.6)

    manifest = {
        "run_id": args.run_id,
        "stage": "fetch",
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "status": "partial" if errors else "success",
        "config": {
            "per_page": args.per_page,
            "lenses": lenses,
            "tags": tags,
            "year_from": YEAR_FROM,
            "year_to": YEAR_TO,
            "mailto_present": bool(args.mailto),
            "api_key_present": bool(args.api_key),
        },
        "files": files,
        "errors": errors,
        "total_returned": total_returned,
        "total_cost_usd": round(total_cost, 6),
    }
    manifest_path = MANIFEST_DIR / f"fetch_openalex_{args.run_id}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nSummary")
    print(f"  run_id: {args.run_id}")
    print(f"  files: {len(files)} (failed: {len(errors)})")
    print(f"  records returned: {total_returned}")
    print(f"  OpenAlex cost: ${total_cost:.4f}")
    print(f"  manifest: {manifest_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
