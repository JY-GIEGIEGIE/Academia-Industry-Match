# 评测模板

本目录存放 v0.1-thin 的空白标注模板与 v0.1 的冻结标注。v0.1 已由 S-09 完成人工首标、独立双标与裁决；标注口径见 `data/spec/eval_spec_v0.1.md`。

> v0.1-thin 完整清洗集在本地 `data/processed/achievements_clean_v0.1-thin.jsonl`，仓库内可用 `data/samples/achievements_sample_v0.1-thin.jsonl` 的 20 条样例对照；v0.1 全量清洗集在组内交接包 `data/processed/achievements_clean_v0.1.jsonl`（300 条），不入库。

## 文件

### 薄切片 `v0.1-thin`

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

### 全量 `v0.1`

来自 S-02 组内交接（2026-11-20），query ID 与 pair ID 与薄切片一致；v0.1 已由 S-09 另行标注，不能直接把薄切片标注复用到全量候选。

| 文件 | 说明 |
| --- | --- |
| `retrieval_queries_v0.1.csv` | 20 条检索 query，20 个候选/条（全量成果）；已冻结（20/20） |
| `retrieval_queries_v0.1.jsonl` | 同上的程序可读版本；`evaluate.py` 实际读这个 |
| `pair_labels_v0.1.csv` | 50 个（需求,成果）对；40 同领域、10 跨领域；已冻结（50/50） |
| `pair_labels_v0.1.jsonl` | 同上的程序可读版本 |
| `eval_templates_manifest_v0.1.json` | 生成清单 |

v0.1-thin 的标注字段仍为空；v0.1 已由 S-09 冻结。导入时用 `--dataset-version v0.1` 会自动读取全量标注，用 `v0.1-thin` 读薄切片。冻结哈希与双标/裁决结果见 `data/manifests/eval_annotation_summary_v0.1.md` 和 `data/manifests/eval_adjudication_v0.1.md`。

### 数据交付 `v0.1.1`

`retrieval_queries_v0.1.1.*` 与 `pair_labels_v0.1.1.*` 是 v0.1 冻结标注的版本化副本，只把 `dataset_version` 元数据改为 `v0.1.1`；标注内容和候选集不变。用于 v0.1.1 新库和 baseline，不重新标注。

## 标注步骤

1. 打开 CSV（Excel 可直接读，UTF-8 BOM）。
2. 检索 query：再看 `candidate_achievement_ids` 对应的成果标题/摘要（v0.1-thin 见 `data/processed/achievements_clean_v0.1-thin.jsonl`；v0.1 见 `data/processed/achievements_clean_v0.1.jsonl`），把相关 ID 写入 `relevant_achievement_ids`，并在 `relevance_grades` 写 `id:2;id:1`。
3. pair：读 `demand_title` 与 `achievement_title`，必要时查全文；按 0/1/2 口径填 `relevance_grade` 和 `rationale`。
4. 20% 双标：第二人另存一份，比较后写 `adjudication`。
5. v0.1 标注已冻结；评测由 S-04 的 `scripts/data/evaluate.py` 读取 JSONL 运行，输出 Recall@10、Precision@5、nDCG@10、MRR。`v0.1-thin` 仍需先完成标注。

## 注意

- 只看技术内容，不看作者/机构/期刊/引用数。
- 不要因为“标题相似”就标相关；要看技术领域、应用场景、TRL、合作模式是否兼容。
- 模拟需求已在 `demand_title` 中标明；标注时按正常需求处理，不因“模拟”降分。
- `q20` 是电网储能钠电材料（英文原文 "cost-effective sodium-ion battery materials for grid storage"）；`消费电子高电压钴酸锂` 是 `dem_020` 的配对需求（pair_039/040），不是 q20。q20 在 v0.1-thin 中相关候选较弱，v0.1 全量后需重新标注。若某 query 确实没有相关候选，在 `notes` 记录原因，评测时将该 query 单列，不强行凑 5 条相关。
- 全量模板的候选来自 300 条成果；标注时以全量候选集为准，不要用薄切片候选替换。
