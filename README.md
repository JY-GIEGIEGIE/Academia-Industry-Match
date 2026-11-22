# Academia-Industry-Match

An agent-driven matching system for academic research outputs and industry needs. It structures paper metadata, aligns concepts across research and industry terminology, and uses LLM reranking to improve match quality.
The MVP targets new energy battery materials and selected energy storage technologies.

## Run the frontend demo

Run all commands below from the root of your cloned `Academia-Industry-Match` repository. No fixed drive, parent directory, or sibling handoff folder is required.

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173/` once the server starts. Demo fixtures ship inside the repository; you only need the private full dataset if you rebuild those fixtures or rerun the full demand checks. See the [frontend README](frontend/README.md) and [private data instructions](data/README.md).

## Review and handoff documents

- [Demand review v0.1](data/manifests/demands_review_v0.1.md): 30 reviewed demands, issues, and seven suggested patches to existing IDs.
- [Demand check evidence](data/manifests/demands_review_checks_v0.1.json): counts, IDs, hashes, and similarity candidates; no full demand text or source snapshots.
- [Frontend delivery and validation](frontend/docs/交付与验收记录.md): local checks and repository-contained screenshots.
- [Frontend design notes](frontend/DESIGN.md): layout, colours, and interaction rules.
- [Frontend path compatibility](frontend/HANDOFF.md): repo-relative startup with in-repo fixtures, optional sample rebuilds, and checks on a renamed checkout.

All links above resolve inside this repository. Private handoff packages and full source snapshots are shared separately by the data owner and can live in any folder you choose.

## Data workstream

- `data/spec/` — data contract, taxonomy v0.1, and evaluation spec.
- `data/samples/` — 20 repo-safe achievement previews (abstracts truncated), 10 anonymized enterprise profiles, and 20 simulated demands.
- `data/eval/` — 20 retrieval queries and 50 pair-label templates.
- `scripts/data/` — OpenAlex fetch, cleaning, thin-slice build, seed generation, evaluation templates, and validation.
- Current status: `v0.1-thin` — 100 real OpenAlex papers (6 main subfields × 15 + flow battery/supercapacitor × 5), generated 2026-11-17/18. See `data/manifests/summary_v0.1-thin.md`.

Data policy: OpenAlex is the primary source; CNKI/Wanfang are not scraped; all enterprise/demand seeds are simulated and marked `is_simulated=true`; full abstracts stay local, and only truncated samples are committed because of publisher copyright.

## Team

- [Data-side work assignment](docs/09-项目管理/数据侧分工安排.md) — first sprint, due 2026-11-22; who does what.
- [Agent handoff instructions](AGENTS.md) — first sprint, due 2026-11-22; read order, task dependencies, do-not-touch list.
- [Repository submission and management rules](docs/09-项目管理/仓库提交与管理规范.md) — branch, commit, PR, data and secret rules.
