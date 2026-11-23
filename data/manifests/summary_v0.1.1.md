# v0.1.1 数据质量报告（第一轮数据侧交付）

> 日期：2026-11-23  
> 新数据库：`s08_v011_20261123`（v0.1 验收库保留不动）  
> 原则：所有修正写入新版本；`v0.1` 不覆盖、不回写。

## 1. 数据规模

| 项目 | 数量 |
| --- | ---: |
| 成果 | 300 |
| 需求 | 100 |
| 企业 | 25 |
| `achievement_tag` | 1269（tech_field 404 / application_scenario 565 / cooperation_mode 300） |
| `achievement_extraction` | 300 |
| `achievement_text` / 画像 | 300 |
| `embedding` | 400（300 成果 + 100 需求） |
| `demand_tag` | 308 |
| `eval_query` / `eval_label` | 20 / 50 |

- 有 primary `tech_field` 的成果：**300/300**。
- 画像覆盖：**300/300**；向量覆盖：**300+100**；维度 1024。
- `embedding_text_hash_mismatch=0`、孤儿向量 0、外键违规 0。
- 第二次重复导入计数不变。

## 2. v0.1.1 修正

- S-07 的 7 条 P1 需求按 `demands_review_v0.1.md` 的 R1—R7 补丁写入，并重算 `content_hash`；R1/R2/R5/R6 的期望交付范围按企业画像微调，避免声称企业不具备的试制能力；R6 标题归一为“水系钠电封装电芯静置析气”。
- 50 处只写日期的 datetime 统一补成 `T00:00:00Z`（20 条需求 × created/updated + 10 家企业 × created）。
- `ach_openalex_W4401101842` 补 `tech_field=electrolyte`（primary），primary 覆盖从 299/300 变为 300/300。
- 所有 `TRL=null` 统一为 `needs_review`，共 58 条；不编造 TRL。
- **画像超过 250 字不再触发 `needs_review`**：业务上完整的技术描述允许超过 250 字；74 条超长画像保留原文，不重写、不重算画像向量。
- 仍为 `needs_review` 的记录：**61 条 = 58 条 TRL=null + 3 条 LLM/retry 待复核**；不是画像长度造成。
- `pending` 239 条；`achievement_tag` 为 1268 pending + W440 的 1 条 human-approved。

## 3. 评测结果

### 3.1 S-04 v0.1.1 正式 baseline

| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR |
| --- | ---: | ---: | ---: | ---: |
| B0 | 0.861 | 0.610 | 0.757 | 0.758 |
| B1 | 0.897 | 0.760 | 0.851 | 0.912 |
| B2（主标签） | 0.887 | 0.730 | 0.832 | 0.912 |

### 3.2 B2-any 补充敏感性

同一批 20 query、同一冻结 query 向量：

| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR |
| --- | ---: | ---: | ---: | ---: |
| B2-any（任一 tech_field） | **0.911** | **0.760** | **0.860** | 0.912 |
| B2-primary（仅主标签） | 0.892 | 0.730 | 0.835 | 0.912 |

说明：B2-any 是补充口径，不替代 S-04 的正式 B2；正式 baseline 仍按 primary 口径。B1/B2 的轻微差异来自 query 向量现场生成与冻结向量的差别，报告中保留。

- 完整补充：`baseline_v0.1.1_s08_addendum.md`
- Top-10：`baseline_v0.1.1_top10.csv`（800 行）
- 错误分析：`error_analysis_v0.1.1.md/.csv`（5 假阳 + 5 假阴，B2-any 补充口径）
- 79→61 的处置台账：`needs_review_disposition_v0.1.1.csv`
- 修正提案：`proposed_data_corrections_v0.1.1.csv`（v0.1.1 已应用；该文件无待应用项）

## 4. 已知限制

- 58 条 `TRL=null` 是“无证据的未知”，保留 null + needs_review；不编造。
- 3 条 LLM/retry 待复核保留 needs_review。
- 30 条标签评测 + 20 条 TRL 边界评测仍需独立 ground truth；本轮不伪造准确率。
- S-09 pair 二次 kappa 0.5714 为已接受例外；S-07 的 7 条 P1 已在 v0.1.1 应用，50 处 datetime 已修正。
- B0 Precision@5 0.610 低于 0.70，作为基线事实保留。

## 5. 证据

- `dataset_v0.1.1.json`、`private_data_v0.1.1.json`
- `extract_v0.1.1-20261123.json`、`embed_v0.1.1-20261123.json`
- `load_report_v0.1.1.md` / `import_v0.1.1.json`（运行时生成，不入库）
- S-04/S-05/S-08 的 v0.1.1 验收记录
