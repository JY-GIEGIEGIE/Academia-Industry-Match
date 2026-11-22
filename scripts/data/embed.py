#!/usr/bin/env python3
"""成果 + 需求全量向量化（1024 维）。

严格依据：
  - data/spec/data_contract_v0.1.md §4.6（embedding 字段）与 §6.4（向量质量规则）
  - scripts/common/llm_client.py（统一走共享客户端，不自己写 HTTP）

向量化文本（契约 §6.4：向量化 capability_profile / need_profile，原始摘要只做证据）：
  - 成果：capability_profile_zh（由 extract_labels.py 产出，落库 text_type=capability_profile）
  - 需求：need_profile（由 title + pain_point + expected_solution + technical_metrics 合成，
    落库 text_type=need_profile）

DashScope 的 API text_type（query/document 指令）按 object_type 区分：
  - 成果作为被检索的“文档”→ text_type="document"
  - 需求作为发起匹配的“查询”→ text_type="query"
  两者分别调用 embed_texts，落库的 text_type 仍保持 capability_profile / need_profile。

输入：
  data/processed/capability_profiles_<version>.jsonl  （extract_labels.py 产出）
  需求：薄切片默认 data/samples/demands_seed_v0.1.jsonl（20 条）；
       全量默认 data/processed/demands_<version>.jsonl（100 条），可用 --demands 覆盖。

输出：
  data/processed/embeddings_<version>.jsonl  每条记录含 model/dim/text_hash/vector
  data/manifests/embed_<run-id>.json         运行清单

用法：
  # 环境自检（不调用 API）
  python scripts/common/llm_client.py --check

  # 薄切片（默认读 20 条样例需求）
  python scripts/data/embed.py --version v0.1-thin

  # 全量（默认读 data/processed/demands_v0.1.jsonl）
  python scripts/data/embed.py --version v0.1
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

SPRINT = "2026-11-22"
EMBEDDING_DIM = 1024


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_ROOT.resolve()))
    except ValueError:
        return str(path)


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


def _default_demands_path(version: str) -> Path:
    """按版本决定需求默认路径：薄切片用样例，全量用 processed。"""
    if version == "v0.1-thin":
        return SAMPLE_DIR / "demands_seed_v0.1.jsonl"
    return PROCESSED_DIR / f"demands_{version}.jsonl"


def _write_embeddings(
    fh,
    tasks: list[tuple[str, str, str | None]],
    vectors: list[list[float]],
    *,
    object_type: str,
    text_type: str,
    model: str,
    dim: int,
    dataset_version: str,
) -> int:
    written = 0
    for (oid, text, src_hash), vec in zip(tasks, vectors):
        th = src_hash or text_hash(text)
        if src_hash and src_hash != text_hash(text):
            print(f"[警告] {oid} 的 text_hash 与文本不匹配，以文本为准重算。", file=sys.stderr)
            th = text_hash(text)
        record = {
            "embedding_id": f"emb_{object_type}_{oid}_{text_type}",
            "object_type": object_type,
            "object_id": oid,
            "text_type": text_type,
            "model": model,
            "dim": dim,
            "text_hash": th,
            "vector": vec,
            "dataset_version": dataset_version,
            "created_at": _now_utc(),
        }
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        written += 1
    return written


def run(args: argparse.Namespace) -> int:
    profiles_path = Path(args.profiles) if args.profiles else PROCESSED_DIR / f"capability_profiles_{args.version}.jsonl"
    demands_path = Path(args.demands) if args.demands else _default_demands_path(args.version)
    out_path = Path(args.output) if args.output else PROCESSED_DIR / f"embeddings_{args.version}.jsonl"

    if not profiles_path.exists():
        print(f"[错误] 找不到能力画像文件：{profiles_path}", file=sys.stderr)
        print("       请先运行 extract_labels.py 生成 capability_profiles。", file=sys.stderr)
        return 2
    if not demands_path.exists():
        print(f"[错误] 找不到需求文件：{demands_path}", file=sys.stderr)
        if args.version != "v0.1-thin":
            print("       全量需求应位于 data/processed/demands_<version>.jsonl，或用 --demands 显式指定。", file=sys.stderr)
        return 2

    try:
        client = DashScopeClient()
    except LlmClientError as exc:
        print(f"[错误] 初始化共享客户端失败：{exc}", file=sys.stderr)
        print("       请先 `python scripts/common/llm_client.py --check` 核对 .env。", file=sys.stderr)
        return 2

    profiles = _load_jsonl(profiles_path)
    demands = _load_jsonl(demands_path)

    # 组装任务并统计缺失（空画像/空需求不计入任务，但计入覆盖率分母）。
    ach_tasks: list[tuple[str, str, str | None]] = []  # (object_id, text, src_hash)
    profile_missing = 0
    for p in profiles:
        text = (p.get("text") or "").strip()
        if not text:
            profile_missing += 1
            print(f"[警告] 空画像（跳过）：{p.get('achievement_id', '?')}", file=sys.stderr)
            continue
        src_hash = p.get("text_hash") if isinstance(p.get("text_hash"), str) else None
        ach_tasks.append((p.get("achievement_id", "?"), text, src_hash))

    demand_tasks: list[tuple[str, str, str | None]] = []
    demand_missing = 0
    for d in demands:
        text = _need_profile_text(d)
        if not text:
            demand_missing += 1
            print(f"[警告] 空需求画像（跳过）：{d.get('demand_id', '?')}", file=sys.stderr)
            continue
        demand_tasks.append((d.get("demand_id", "?"), text, None))

    expected = len(profiles) + len(demands)
    if expected == 0:
        print("[错误] 没有可向量化的输入（画像与需求均为空）。", file=sys.stderr)
        return 2

    model = client.embedding_model
    dim = int(client.embedding_dim)
    if dim != EMBEDDING_DIM:
        print(f"[错误] embedding 维度 {dim} != {EMBEDDING_DIM}，请检查 .env 的 EMBEDDING_DIM。", file=sys.stderr)
        return 1

    run_id = args.run_id or f"{args.version}-{datetime.now(timezone.utc):%Y%m%d}"
    started = _now_utc()

    print(f"成果画像：{len(profiles)} 条（空 {profile_missing}）；需求：{len(demands)} 条（空 {demand_missing}）")
    print(f"待向量化：{len(ach_tasks) + len(demand_tasks)} 条（model={model} dim={dim}）")
    print(f"输出：{out_path}\n")

    # 按 object_type 分两组，分别用 document / query 指令调用。
    try:
        ach_vectors = (
            client.embed_texts([t[1] for t in ach_tasks], text_type="document", dimensions=dim)
            if ach_tasks else []
        )
        demand_vectors = (
            client.embed_texts([t[1] for t in demand_tasks], text_type="query", dimensions=dim)
            if demand_tasks else []
        )
    except LlmClientError as exc:
        print(f"[错误] 向量化失败：{exc}", file=sys.stderr)
        return 1

    if len(ach_vectors) != len(ach_tasks) or len(demand_vectors) != len(demand_tasks):
        print(f"[错误] 返回向量条数不符：成果 {len(ach_vectors)}/{len(ach_tasks)}，"
              f"需求 {len(demand_vectors)}/{len(demand_tasks)}。", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        written += _write_embeddings(
            fh, ach_tasks, ach_vectors, object_type="achievement",
            text_type="capability_profile", model=model, dim=dim, dataset_version=args.version,
        )
        written += _write_embeddings(
            fh, demand_tasks, demand_vectors, object_type="demand",
            text_type="need_profile", model=model, dim=dim, dataset_version=args.version,
        )

    missing = profile_missing + demand_missing
    coverage = written / expected if expected else 0.0
    ok = missing == 0 and written == expected
    status = "success" if ok else ("failed" if written == 0 else "partial")

    manifest = {
        "run_id": run_id,
        "stage": "embed",
        "sprint": SPRINT,
        "status": status,
        "dataset_version": args.version,
        "model": model,
        "dim": dim,
        "profiles_path": _relpath(profiles_path),
        "demands_path": _relpath(demands_path),
        "output_path": _relpath(out_path),
        "started_at": started,
        "finished_at": _now_utc(),
        "input_achievements": len(profiles),
        "input_demands": len(demands),
        "expected": expected,
        "output_count": written,
        "profile_missing": profile_missing,
        "demand_missing": demand_missing,
        "coverage": coverage,
        "git_commit": _git_commit(),
        "args": vars(args),
    }
    manifest_path = MANIFEST_DIR / f"embed_{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：写 {written}/{expected} 条向量（覆盖率 {coverage:.1%}）")
    if profile_missing or demand_missing:
        print(f"缺失：画像 {profile_missing} 条、需求 {demand_missing} 条（覆盖率不足 100%）")
    print(f"清单：{manifest_path}")
    return 0 if ok else 1


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
    parser.add_argument("--demands", default=None, help="需求 jsonl（薄切片默认 samples/demands_seed_v0.1.jsonl；全量默认 data/processed/demands_<version>.jsonl）")
    parser.add_argument("--output", default=None, help="输出路径（默认 data/processed/embeddings_<version>.jsonl）")
    parser.add_argument("--run-id", default=None, help="运行 ID（默认 <version>-<日期>）")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
