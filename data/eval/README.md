# 评测模板

本目录存放 v0.1-thin 与 v0.1 全量的检索 query 与 pair 标注模板。标注口径见 `data/spec/eval_spec_v0.1.md`。

> v0.1-thin 完整清洗集在本地 `data/processed/achievements_clean_v0.1-thin.jsonl`，仓库内可用 `data/samples/achievements_sample_v0.1-thin.jsonl` 的 20 条样例对照；v0.1 全量清洗集在组内交接包 `data/processed/achievements_clean_v0.1.jsonl`（300 条），不入库。

## 文件

| 文件 | 说明 |
| --- | --- |
| `retrieval_queries_v0.1-thin.csv` | 20 条检索 query；`relevant_achievement_ids` / `relevance_grades` / `annotator` 待填 |
| `retrieval_queries_v0.1-thin.jsonl` | 同上的程序可读版本；`candidate_achievement_ids` 为数组 |
| `pair_labels_v0.1-thin.csv` | 50 个（需求,成果）对；`relevance_grade` / `rationale` / `annotator` / `adjudication` 待填 |
| `pair_labels_v0.1-thin.jsonl` | 同上的程序可读版本 |
| `eval_templates_manifest_v0.1-thin.json` | 薄切片生成清单（数量、来源、输出路径） |
| `retrieval_queries_v0.1.csv` | 20 条 v0.1 检索 query；`relevant_achievement_ids` / `relevance_grades` / `annotator` 待填 |
| `retrieval_queries_v0.1.jsonl` | 同上的程序可读版本；`candidate_achievement_ids` 为数组 |
| `pair_labels_v0.1.csv` | 50 个 v0.1（需求,成果）对；`relevance_grade` / `rationale` / `annotator` / `adjudication` 待填 |
| `pair_labels_v0.1.jsonl` | 同上的程序可读版本 |
| `eval_templates_manifest_v0.1.json` | v0.1 生成清单（300 成果 / 20 需求 / 20 query / 50 pair） |

## 标注步骤

1. 打开 CSV（Excel 可直接读，UTF-8 BOM）。
2. 检索 query：再看 `candidate_achievement_ids` 对应的成果标题/摘要（v0.1-thin 见 `data/processed/achievements_clean_v0.1-thin.jsonl`；v0.1 见 `data/processed/achievements_clean_v0.1.jsonl`），把相关 ID 写入 `relevant_achievement_ids`，并在 `relevance_grades` 写 `id:2;id:1`。
3. pair：读 `demand_title` 与 `achievement_title`，必要时查全文；按 0/1/2 口径填 `relevance_grade` 和 `rationale`。
4. 20% 双标：第二人另存一份，比较后写 `adjudication`。
5. 标注完成后运行评测脚本（待实现 `evaluate.py`），输出 Recall@10、Precision@5、nDCG@10。

## 注意

- 只看技术内容，不看作者/机构/期刊/引用数。
- 不要因为“标题相似”就标相关；要看技术领域、应用场景、TRL、合作模式是否兼容。
- 模拟需求已在 `demand_title` 中标明；标注时按正常需求处理，不因“模拟”降分。
- `q20` 是电网储能钠电材料（英文原文 "cost-effective sodium-ion battery materials for grid storage"）；`消费电子高电压钴酸锂` 是 `dem_020` 的配对需求（pair_039/040），不是 q20。q20 在 v0.1-thin 中相关候选较弱，v0.1 全量后需重新标注。若某 query 确实没有相关候选，在 `notes` 记录原因，评测时将该 query 单列，不强行凑 5 条相关。
