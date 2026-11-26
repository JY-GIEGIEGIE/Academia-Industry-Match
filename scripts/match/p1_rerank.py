#!/usr/bin/env python3
"""P1 LLM 精排：对 B2 匹配结果生成 risk / evidence / 自然语言理由（S-10，第二轮冲刺）。

依据：
  - docs/02-需求分析/数据API契约_v0.1.md §6.4（risk/evidence 结构）
  - data/spec/data_contract_v0.1.md §4.10（match_score 字段）

做什么：
  1. 读取 B2 匹配结果（matches_b2_<version>.jsonl）。
  2. 对每条 match 拼需求/成果上下文，调 llm_client.chat_json 生成 reason / risk / evidence。
  3. 写死回退：try-except 包裹，只要 API 报错/超时/输出非法，直接保留 B2 结果
     （risk/evidence 仍为 null，reason 仍为 B2 规则理由），绝不中断任务。

输入（data/processed/，均可 --xxx 覆盖）：
  matches_b2_<version>.jsonl            B2 匹配结果（待精排）
  demands_<version>.jsonl               需求上下文
  achievements_labeled_<version>.jsonl  成果标签/TRL/IP/指标
  capability_profiles_<version>.jsonl   成果中文画像
  achievements_clean_<version>.jsonl    成果原始标题/摘要（evidence 原文来源）

输出：
  data/processed/matches_p1_<version>.jsonl
  data/manifests/match_p1_<version>.json

用法：
  python scripts/match/p1_rerank.py --version v0.1.2
  python scripts/match/p1_rerank.py --version v0.1.2 --limit 20   # 演示 Top-20
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA_SCRIPT_DIR = _ROOT / "scripts" / "data"
for _p in (str(_ROOT), str(_DATA_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import MANIFEST_DIR, PROCESSED_DIR  # noqa: E402
from scripts.common.llm_client import DashScopeClient, LlmClientError  # noqa: E402

SPRINT = "2026-11-29"
TAXONOMY_VERSION = "v0.1"
PROMPT_VERSION = "v0.1"
MAX_ABSTRACT_CHARS = 1500

SYSTEM_PROMPT = """你是产学研技术转化匹配的精排专家。给定一条企业需求与一项技术成果的字段，评估二者匹配的风险、证据与推荐理由。

严格规则：
1. 只依据给定字段，不得编造字段之外的信息；evidence.snippets 的 text 必须逐字取自给定字段原文。
2. 风险四维 score 用 1—5 整数（1=低风险，5=高风险）：
   - technical：成果 TRL 与需求 required_trl 的差距、技术路线兼容性；
   - market：成果应用场景与需求/企业场景的匹配度；
   - ip：成果 ip_status 与知识产权清晰度（论文默认 unknown，不得推断为已授权）；
   - collaboration：合作模式兼容性、地区/规模匹配度。
   - overall：summary 一句话综合提示 + mitigation 1—3 条可执行建议。
3. reason：自然语言推荐理由，100 字内，说明匹配依据与主要风险，不夸大。
4. evidence.tag_matches 的 code 只能是给定字段里出现的 taxonomy code。
5. 只输出 JSON，不要 markdown 代码块。

输出 schema（严格按此结构）：
{
  "reason": "自然语言推荐理由",
  "risk": {
    "technical": {"score": 4, "description": "成果 TRL 4，低于需求 TRL 5，需中试验证。"},
    "market": {"score": 2, "description": "应用场景与需求匹配。"},
    "ip": {"score": 3, "description": "论文未披露专利状态，IP 证据不足。"},
    "collaboration": {"score": 3, "description": "合作模式兼容。"},
    "overall": {"summary": "技术方向匹配，主要风险在中试放大。", "mitigation": ["先做中试可行性验证", "开展 IP 尽调"]}
  },
  "evidence": {
    "tag_matches": [{"dimension": "tech_field", "code": "electrolyte", "achievement_confidence": 0.93, "demand_confidence": null}],
    "snippets": [{"side": "achievement", "field": "abstract_original", "text": "原文摘录", "source_ref": "achievement.abstract_original"}],
    "metric_matches": [{"name": "离子电导率", "achievement_value": "12", "required_value": ">=10", "unit": "mS/cm", "matched": true}]
  }
}"""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_ROOT.resolve()))
    except ValueError:
        return str(path)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
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


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _demand_context(demand: dict) -> dict:
    return {
        "demand_id": demand.get("demand_id"),
        "title": demand.get("title"),
        "pain_point": demand.get("pain_point"),
        "expected_solution": demand.get("expected_solution"),
        "tech_fields": demand.get("tech_fields"),
        "application_scenarios": demand.get("application_scenarios"),
        "required_trl": demand.get("required_trl"),
        "cooperation_modes": demand.get("cooperation_modes"),
        "technical_metrics": demand.get("technical_metrics"),
    }


def _achievement_context(ach_label: dict, profile: dict | None, ach_clean: dict | None) -> dict:
    tags = ach_label.get("tags") or []
    techs = [t for t in tags if t.get("dimension") == "tech_field"]
    primary = next((t for t in techs if t.get("is_primary")), None) or (techs[0] if techs else None)
    scenarios = [t.get("code") for t in tags if t.get("dimension") == "application_scenario"]
    abstract = (ach_clean or {}).get("abstract_original") or ""
    if len(abstract) > MAX_ABSTRACT_CHARS:
        abstract = abstract[:MAX_ABSTRACT_CHARS] + "…"
    ext = ach_label.get("extraction") or {}
    return {
        "achievement_id": ach_label.get("achievement_id"),
        "title": (ach_clean or {}).get("title_original"),
        "abstract": abstract,
        "profile": (profile or {}).get("text"),
        "primary_tech_field": primary.get("code") if primary else None,
        "application_scenarios": scenarios,
        "trl": ext.get("trl"),
        "ip_status": ext.get("ip_status"),
        "material_system": ext.get("material_system"),
        "key_metrics": ext.get("key_metrics"),
    }


def _build_user_message(demand_ctx: dict, ach_ctx: dict) -> str:
    return (
        "请评估下面需求与成果的匹配，只输出 JSON。\n\n"
        "【企业需求】\n"
        + json.dumps(demand_ctx, ensure_ascii=False, indent=2)
        + "\n\n【技术成果】\n"
        + json.dumps(ach_ctx, ensure_ascii=False, indent=2)
    )


def rerank_one(
    client: DashScopeClient,
    match: dict,
    demand_ctx: dict,
    ach_ctx: dict,
    *,
    model: str,
    prompt_version: str,
) -> tuple[dict, bool]:
    """精排一条 match；返回 (match, ok)。失败回退 B2（match 原样）。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(demand_ctx, ach_ctx)},
    ]
    try:
        result = client.chat_json(messages, model=model, max_tokens=2048, temperature=0.2)
        if not isinstance(result, dict) or not result.get("reason"):
            raise ValueError("LLM 输出缺少 reason")
        updated = dict(match)
        updated["reason"] = result.get("reason") or match.get("reason")
        updated["risk"] = result.get("risk")
        updated["evidence"] = result.get("evidence")
        updated["model"] = model
        updated["prompt_version"] = prompt_version
        return updated, True
    except Exception as exc:  # noqa: BLE001 —— API 报错/超时/输出非法一律回退 B2
        print(f"[警告] 精排失败，回退 B2：{match.get('match_id')} — {exc}", file=sys.stderr)
        return match, False


def run(args: argparse.Namespace) -> int:
    matches_path = Path(args.matches) if args.matches else PROCESSED_DIR / f"matches_b2_{args.version}.jsonl"
    demands_path = Path(args.demands) if args.demands else PROCESSED_DIR / f"demands_{args.version}.jsonl"
    labels_path = Path(args.labels) if args.labels else PROCESSED_DIR / f"achievements_labeled_{args.version}.jsonl"
    profiles_path = Path(args.profiles) if args.profiles else PROCESSED_DIR / f"capability_profiles_{args.version}.jsonl"
    achievements_path = Path(args.achievements) if args.achievements else PROCESSED_DIR / f"achievements_clean_{args.version}.jsonl"
    out_path = Path(args.output) if args.output else PROCESSED_DIR / f"matches_p1_{args.version}.jsonl"

    for name, path in (("matches", matches_path), ("demands", demands_path), ("labels", labels_path),
                       ("profiles", profiles_path), ("achievements", achievements_path)):
        if not path.exists():
            print(f"[错误] 找不到 {name} 文件：{path}", file=sys.stderr)
            return 2

    matches = _read_jsonl(matches_path)
    demands = {d.get("demand_id"): d for d in _read_jsonl(demands_path) if d.get("demand_id")}
    labels = {r.get("achievement_id"): r for r in _read_jsonl(labels_path) if r.get("achievement_id")}
    profiles = {p.get("achievement_id"): p for p in _read_jsonl(profiles_path) if p.get("achievement_id")}
    achievements = {a.get("achievement_id"): a for a in _read_jsonl(achievements_path) if a.get("achievement_id")}

    try:
        client = DashScopeClient()
    except LlmClientError as exc:
        print(f"[错误] 初始化共享客户端失败：{exc}", file=sys.stderr)
        print("       请先 `python scripts/common/llm_client.py --check` 核对 .env。", file=sys.stderr)
        return 2

    model = args.model or client.chat_model
    todo = matches if args.limit is None else matches[: args.limit]
    print(f"待精排：{len(todo)} 条（model={model} prompt_version={PROMPT_VERSION}）")

    out: list[dict] = []
    reranked = fallback = skipped = 0
    for m in todo:
        demand = demands.get(m.get("demand_id"))
        ach_label = labels.get(m.get("achievement_id"))
        if demand is None or ach_label is None:
            out.append(m)  # 缺上下文无法精排，保留 B2
            skipped += 1
            continue
        dctx = _demand_context(demand)
        actx = _achievement_context(ach_label, profiles.get(m.get("achievement_id")),
                                    achievements.get(m.get("achievement_id")))
        updated, ok = rerank_one(client, m, dctx, actx, model=model, prompt_version=PROMPT_VERSION)
        out.append(updated)
        if ok:
            reranked += 1
        else:
            fallback += 1

    _write_jsonl(out_path, out)

    manifest = {
        "sprint": SPRINT,
        "task": "S-10",
        "stage": "match",
        "status": "success",
        "dataset_version": args.version,
        "taxonomy_version": TAXONOMY_VERSION,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "matches_path": _relpath(matches_path),
        "output_path": _relpath(out_path),
        "input_matches": len(matches),
        "processed": len(todo),
        "reranked": reranked,
        "fallback_b2": fallback,
        "skipped_missing_context": skipped,
        "git_commit": _git_commit(),
        "args": vars(args),
    }
    manifest_path = MANIFEST_DIR / f"match_p1_{args.version}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：精排 {reranked} 条、回退 B2 {fallback} 条、缺上下文跳过 {skipped} 条")
    print(f"输出：{out_path}")
    print(f"清单：{manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="P1 LLM 精排：生成 risk / evidence / 自然语言理由，失败回退 B2",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", default="v0.1.2", help="数据版本，决定输入/输出文件名")
    parser.add_argument("--matches", default=None, help="B2 匹配 jsonl（默认 data/processed/matches_b2_<version>.jsonl）")
    parser.add_argument("--demands", default=None, help="需求 jsonl（默认 data/processed/demands_<version>.jsonl）")
    parser.add_argument("--labels", default=None, help="标签 jsonl（默认 data/processed/achievements_labeled_<version>.jsonl）")
    parser.add_argument("--profiles", default=None, help="画像 jsonl（默认 data/processed/capability_profiles_<version>.jsonl）")
    parser.add_argument("--achievements", default=None, help="清洗成果 jsonl（默认 data/processed/achievements_clean_<version>.jsonl）")
    parser.add_argument("--output", default=None, help="输出 jsonl（默认 data/processed/matches_p1_<version>.jsonl）")
    parser.add_argument("--model", default=None, help="覆盖精排模型（默认读 .env 的 QWEN_CHAT_MODEL）")
    parser.add_argument("--limit", type=int, default=None, help="只精排前 N 条（演示用）")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
