#!/usr/bin/env python3
"""成果 + 需求全量向量化（1024 维）。

严格依据：
  - data/spec/data_contract_v0.1.md §4.6（embedding 字段）与 §6.4（向量质量规则）
  - scripts/common/llm_client.py（统一走共享客户端，不自己写 HTTP）

向量化文本（契约 §6.4：向量化 capability_profile / need_profile，原始摘要只做证据）：
  - 成果：capability_profile_zh（由 extract_labels.py 产出，text_type=capability_profile）
  - 需求：need_profile（由 title + pain_point + expected_solution + technical_metrics 合成）

输入：
  data/processed/capability_profiles_<version>.jsonl  （extract_labels.py 产出）
  data/samples/demands_seed_v0.1.jsonl（薄切片 20 条）或 data/processed/demands_v0.1.jsonl（全量 100 条）

输出：
  data/processed/embeddings_<version>.jsonl  每条记录含 model/dim/text_hash/vector
  data/manifests/embed_<run-id>.json         运行清单

用法：
  # 环境自检（不调用 API）
  python scripts/common/llm_client.py --check

  # 薄切片
  python scripts/data/embed.py --version v0.1-thin

  # 全量（切 version + 指定 100 条需求）
  python scripts/data/embed.py --version v0.1 --demands data/processed/demands_v0.1.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import MANIFEST_DIR, PROCESSED_DIR, SAMPLE_DIR  # noqa: E402
from scripts.common.llm_client import DashScopeClient, LlmClientError, text_hash  # noqa: E402


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


def _need_profile_text(demand: dict) -> str:
    """合成需求侧的 need_profile 文本（契约 §4.6 text_type=need_profile）。"""
    parts: list[str] = []
    for key in ("title", "pain_point", "expected_solution"):
        value = (demand.get(key) or "").strip()
        if value:
            parts.append(value)
    metrics = demand.get("technical_metrics")
    if isinstance(metrics, list):
        for m in metrics:
            if isinstance(m, dict):
                seg = " ".join(
                    str(m.get(k, "")) for k in ("name", "value", "unit") if m.get(k)
                )
                if seg.strip():
                    parts.append(seg.strip())
    return "。".join(parts)


def run(args: argparse.Namespace) -> int:
    profiles_path = Path(args.profiles) if args.profiles else PROCESSED_DIR / f"capability_profiles_{args.version}.jsonl"
    demands_path = Path(args.demands) if args.demands else SAMPLE_DIR / "demands_seed_v0.1.jsonl"
    out_path = Path(args.output) if args.output else PROCESSED_DIR / f"embeddings_{args.version}.jsonl"

    if not profiles_path.exists():
        print(f"[错误] 找不到能力画像文件：{profiles_path}", file=sys.stderr)
        print("       请先运行 extract_labels.py 生成 capability_profiles。", file=sys.stderr)
        return 2
    if not demands_path.exists():
        print(f"[错误] 找不到需求文件：{demands_path}", file=sys.stderr)
        return 2

    try:
        client = DashScopeClient()
    except LlmClientError as exc:
        print(f"[错误] 初始化共享客户端失败：{exc}", file=sys.stderr)
        print("       请先 `python scripts/common/llm_client.py --check` 核对 .env。", file=sys.stderr)
        return 2

    profiles = _load_jsonl(profiles_path)
    demands = _load_jsonl(demands_path)

    # 组装待向量化任务：(object_type, object_id, text_type, text, source_text_hash)
    tasks: list[tuple[str, str, str, str, str | None]] = []
    for p in profiles:
        text = (p.get("text") or "").strip()
        if not text:
            print(f"[警告] 跳过空画像：{p.get('achievement_id', '?')}", file=sys.stderr)
            continue
        src_hash = p.get("text_hash") if isinstance(p.get("text_hash"), str) else None
        tasks.append(("achievement", p["achievement_id"], "capability_profile", text, src_hash))
    for d in demands:
        text = _need_profile_text(d)
        if not text:
            print(f"[警告] 跳过空需求画像：{d.get('demand_id', '?')}", file=sys.stderr)
            continue
        tasks.append(("demand", d["demand_id"], "need_profile", text, None))

    if not tasks:
        print("[错误] 没有可向量化的文本。", file=sys.stderr)
        return 2

    model = client.embedding_model
    dim = client.embedding_dim
    run_id = args.run_id or f"embed-{args.version}-{datetime.now(timezone.utc):%Y%m%d}"
    started = _now_utc()

    print(f"成果画像：{len(profiles)} 条；需求：{len(demands)} 条")
    print(f"待向量化：{len(tasks)} 条（model={model} dim={dim}）")
    print(f"输出：{out_path}\n")

    texts = [t[3] for t in tasks]
    try:
        vectors = client.embed_texts(texts, text_type="document", dimensions=dim)
    except LlmClientError as exc:
        print(f"[错误] 向量化失败：{exc}", file=sys.stderr)
        return 1

    if len(vectors) != len(tasks):
        print(f"[错误] 返回 {len(vectors)} 条向量，期望 {len(tasks)} 条。", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for (otype, oid, ttype, text, src_hash), vec in zip(tasks, vectors):
            # 与文本表 text_hash 保持一致；对合成文本则现算。
            th = src_hash or text_hash(text)
            if src_hash and src_hash != text_hash(text):
                print(f"[警告] {oid} 的 text_hash 与文本不匹配，以文本为准重算。", file=sys.stderr)
                th = text_hash(text)
            record = {
                "embedding_id": f"emb_{otype}_{oid}_{ttype}",
                "object_type": otype,
                "object_id": oid,
                "text_type": ttype,
                "model": model,
                "dim": dim,
                "text_hash": th,
                "vector": vec,
                "dataset_version": args.version,
                "created_at": _now_utc(),
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    manifest = {
        "run_id": run_id,
        "stage": "embed",
        "dataset_version": args.version,
        "model": model,
        "dim": dim,
        "profiles_path": str(profiles_path),
        "demands_path": str(demands_path),
        "output_path": str(out_path),
        "started_at": started,
        "finished_at": _now_utc(),
        "achievement_count": sum(1 for t in tasks if t[0] == "achievement"),
        "demand_count": sum(1 for t in tasks if t[0] == "demand"),
        "total": len(tasks),
        "written": written,
        "coverage": written / len(tasks) if tasks else 0.0,
        "git_commit": _git_commit(),
        "args": vars(args),
    }
    manifest_path = MANIFEST_DIR / f"embed_{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：写 {written}/{len(tasks)} 条向量（覆盖率 {manifest['coverage']:.1%}）")
    print(f"清单：{manifest_path}")
    return 0 if written == len(tasks) else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="成果 + 需求全量向量化（1024 维）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default="v0.1-thin", help="数据版本，决定输出文件名与 dataset_version")
    parser.add_argument("--profiles", default=None, help="能力画像 jsonl（默认 data/processed/capability_profiles_<version>.jsonl）")
    parser.add_argument("--demands", default=None, help="需求 jsonl（默认 data/samples/demands_seed_v0.1.jsonl）")
    parser.add_argument("--output", default=None, help="输出路径（默认 data/processed/embeddings_<version>.jsonl）")
    parser.add_argument("--run-id", default=None, help="运行 ID（默认 embed-<version>-<日期>）")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
