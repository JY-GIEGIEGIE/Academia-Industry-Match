# S-08 v0.1 评测补充报告（v0.1）

- 生成时间：2026-11-23T06:34:50.136793+00:00
- 性质：**只读补充分析**，不替代 S-04 的正式 baseline，不改数据库、不改 `data/processed/`。
- 输入 query：`data/eval/retrieval_queries_v0.1.jsonl` sha256 `3de11bf3264a3549a56fa801628aa9cf920c4c09408d3a6542d2a62a1d0ab897`
- 输入 labels：`data/processed/achievements_labeled_v0.1.jsonl` sha256 `fa1eb22990ec0157e2c8eb98628304160402df671f3d334999af48f700fbf73c`
- 输入 embeddings：`data/processed/embeddings_v0.1.jsonl` sha256 `cf28771142c2276b39af6986f47f940619cab636636e85ea09bcfd5af6924459`
- 冻结 query 向量：`data/interim/s04_eval_query_vectors_v0.1.jsonl` sha256 `46fba2517f449bcc27f80fb69aae34b34363c362cac2453358f83eae1d9e258b`

## 指标（同一套 20 query、同一冻结 query 向量）

| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR | 有效 query 数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 | 0.861 | 0.610 | 0.757 | 0.758 | 20 |
| B1 | 0.897 | 0.760 | 0.852 | 0.912 | 20 |
| B2（任一 tech_field） | 0.911 | 0.770 | 0.861 | 0.912 | 20 |
| B2-primary（仅主标签） | 0.892 | 0.740 | 0.836 | 0.912 | 20 |

说明：B2-any 是 S-08 的补充敏感性口径；B2-primary 是 S-04 原有的正式口径，本报告重算仅为同一 query 向量下对照。B1 的 Precision@5 与 S-04 报告的 0.770 有差异，原因是本次使用冻结 query 向量；不修改 S-04 历史报告。

- B2 空过滤 query 数：0；B2-primary 空过滤 query 数：0。
- 成果向量模型：['qwen3.7-text-embedding-flash']；向量数：300。

## 明细

- Top-10：`data/manifests/baseline_v0.1_top10.csv`
- 错误分析：`data/manifests/error_analysis_v0.1.md` / `.csv`

## 边界

- 本报告不修改 `data/eval/` 的冻结标注，不修改 S-04 的 `baseline_v0.1.md`。
- 任何正式口径调整都必须由 PM 明确签收，并保留原 S-04 报告。