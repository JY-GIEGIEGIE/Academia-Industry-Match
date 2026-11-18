# Academia-Industry-Match
An agent-driven system that performs bidirectional matching between academic research outputs and published industry needs, utilizing structured publication management, cross-semantic-space mapping, and LLM-based reranking to achieve more effective alignment between academia and industry.
As MVP, we focus on new energy battery materials, and involve some new types of energy storage technologies.

## Data workstream

- `data/spec/` — data contract, taxonomy v0.1, and evaluation spec.
- `data/samples/` — 20 repo-safe achievement previews (abstracts truncated), 10 anonymized enterprise profiles, and 20 simulated demands.
- `data/eval/` — 20 retrieval queries and 50 pair-label templates.
- `scripts/data/` — OpenAlex fetch, cleaning, thin-slice build, seed generation, evaluation templates, and validation.
- Current status: `v0.1-thin` — 100 real OpenAlex papers (6 main subfields × 15 + flow battery/supercapacitor × 5), generated 2026-11-17/18. See `data/manifests/summary_v0.1-thin.md`. The full 100-record set ships in handoff package v3 under `data/processed/` and is not committed; v2 and earlier packages are void.

Data policy: OpenAlex is the primary source; CNKI/Wanfang are not scraped; all enterprise/demand seeds are simulated and marked `is_simulated=true`; full abstracts stay local, and only truncated samples are committed because of publisher copyright.

## Team

- [Data-side work assignment](docs/09-项目管理/数据侧分工安排.md) — first sprint, due 2026-11-22 noon; who does what.
- [Data-side handoff notes](docs/09-项目管理/数据侧交接说明_v0.1-thin.md) — v3 package status, verification results and open questions; v2 and earlier are void.
- [Agent handoff instructions](AGENTS.md) — first sprint, due 2026-11-22 noon; read order, task dependencies, do-not-touch list.
- [Repository submission and management rules](docs/09-项目管理/仓库提交与管理规范.md) — branch, commit, PR, data and secret rules.
