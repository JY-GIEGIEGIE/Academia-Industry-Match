# v0.1.2 数据质量报告（第一轮数据侧交付）

> 日期：2026-11-23
> 新数据库：`s08_v012_20261123`（v0.1/v0.1.1 保留）
> 版本：v0.1.2；taxonomy v0.1；embedding qwen3.7-text-embedding-flash-1024-v1

## 1. 数据规模

| 项目 | 数量 |
| --- | ---: |
| 成果 | 300 |
| 需求 | 100 |
| 企业 | 25 |
| `achievement_tag` | 811（tech_field 404 / application_scenario 107 / cooperation_mode 300） |
| `achievement_extraction` | 300（pending 239 / needs_review 61） |
| `achievement_text` | 300 |
| `embedding` | 400（300+100） |
| `demand_tag` | 308 |
| `eval_query` / `eval_label` | 20 / 50 |

primary `tech_field` 300/300；画像/向量覆盖 100%；无维度、外键、孤儿向量、哈希错误。第二次导入计数不变。

## 2. v0.1.2 修正

- 基于 30 条人工标签评测，删除 `application_scenario` 置信度 <0.9 的 458 条低置信场景标签。
- 场景标签 565→107；`achievement_tag` 1269→811。
- 画像、需求、成就向量、TRL 不变；不重写画像，不重算成就向量。
- 保留 61 条 `needs_review`：58 条 TRL=null + 3 条 LLM/retry。
- 画像 >250 字按业务口径接受。

## 3. 人工评测

| 指标 | v0.1.1 | v0.1.2 | 目标 |
| --- | ---: | ---: | ---: |
| 主 `tech_field` | 30/30（100%） | 30/30（100%） | ≥90% |
| `tech_field` 多标签精确集合 | 23/30（76.7%） | 23/30（76.7%） | 如按集合计未达 |
| `application_scenario` 精确集合 | 9/30（30%） | **26/30（86.7%）** | ≥85% |
| `cooperation_mode` | 27/30（90%） | 27/30（90%） | ≥90% |
| TRL | 19/20 null；1 待全文 | 同左 | 无数值 MAE |

详见 `docs/09-项目管理/评测标注/S-08_人工评测结果_v0.1.2.md`。

## 4. 评测

- 正式 B0/B1/B2（主标签）：`0.861/0.610/0.757/0.758`、`0.897/0.760/0.851/0.912`、`0.887/0.730/0.832/0.912`
- B2-any 补充：`0.911/0.760/0.860/0.912`
- Top-10 800 行、5+5 错误分析、B2 敏感性分析已生成

## 5. 已知限制

- `tech_field` 次标签精确集合 76.7%；6 条确认应删次标签，`W7214003609` 的 separator 次标签待确认。
- TRL 19/20 确认 null，`ach_openalex_W4409366487` 待全文；无可用 MAE。
- 0.9 场景阈值在 30 条样本上校准，不是独立留出集。
- B0 Precision@5 0.610 < 0.70，作为基线事实保留。
- S-09 pair 二次 kappa 0.5714 按例外接受。

## 6. 证据

- `dataset_v0.1.2.json`、`private_data_v0.1.2.json`
- `extract_v0.1.2-20261123.json`、`embed_v0.1.2-20261123.json`
- `baseline_v0.1.2.md`、`baseline_v0.1.2_s08_addendum.md`、`baseline_v0.1.2_top10.csv`
- `error_analysis_v0.1.2.md/.csv`、`needs_review_disposition_v0.1.2.csv`
- `load_report_v0.1.2.md` / `import_v0.1.2.json`（运行时生成）
