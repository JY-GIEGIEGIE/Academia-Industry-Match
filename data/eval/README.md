# 评测模板

本目录存放检索 query 与 pair 标注模板，分薄切片（`v0.1-thin`）和全量（`v0.1`）两个版本。标注口径见 `data/spec/eval_spec_v0.1.md`。

> 完整清洗集在本地 `data/processed/`（不入库）：薄切片为 `achievements_clean_v0.1-thin.jsonl`（100 条），全量为 `achievements_clean_v0.1.jsonl`（300 条）。仓库内可用 `data/samples/achievements_sample_v0.1-thin.jsonl` 的 20 条样例对照。

## 文件

### 薄切片 `v0.1-thin`

| 文件 | 说明 |
| --- | --- |
| `retrieval_queries_v0.1-thin.csv` | 20 条检索 query；`relevant_achievement_ids` / `relevance_grades` / `annotator` 待填 |
| `retrieval_queries_v0.1-thin.jsonl` | 同上的程序可读版本；`candidate_achievement_ids` 为数组 |
| `pair_labels_v0.1-thin.csv` | 50 个（需求,成果）对；`relevance_grade` / `rationale` / `annotator` / `adjudication` 待填 |
| `pair_labels_v0.1-thin.jsonl` | 同上的程序可读版本 |
| `eval_templates_manifest_v0.1-thin.json` | 生成清单（数量、来源、输出路径） |

### 全量 `v0.1`

来自 S-02 组内交接（2026-11-20），query ID 与 pair ID 与薄切片一致，可复用同一批标注。

| 文件 | 说明 |
| --- | --- |
| `retrieval_queries_v0.1.csv` | 20 条检索 query，20 个候选/条（全量成果） |
| `retrieval_queries_v0.1.jsonl` | 同上的程序可读版本 |
| `pair_labels_v0.1.csv` | 50 个（需求,成果）对；40 同领域、10 跨领域 |
| `pair_labels_v0.1.jsonl` | 同上的程序可读版本 |
| `eval_templates_manifest_v0.1.json` | 生成清单 |

两个版本的标注字段目前都为空。导入时用 `--dataset-version v0.1` 会自动读取全量模板，用 `v0.1-thin` 读薄切片。

## 标注步骤

1. 打开 CSV（Excel 可直接读，UTF-8 BOM）。
2. 检索 query：再看 `candidate_achievement_ids` 对应的成果标题/摘要——薄切片看 `data/processed/achievements_clean_v0.1-thin.jsonl`（100 条），全量看 `data/processed/achievements_clean_v0.1.jsonl`（300 条）。把相关 ID 写入 `relevant_achievement_ids`，并在 `relevance_grades` 写 `id:2;id:1`。
3. pair：读 `demand_title` 与 `achievement_title`，必要时查全文；按 0/1/2 口径填 `relevance_grade` 和 `rationale`。
4. 20% 双标：第二人另存一份，比较后写 `adjudication`。
5. 标注完成后运行评测脚本（待实现 `evaluate.py`），输出 Recall@10、Precision@5、nDCG@10。

## 注意

- 只看技术内容，不看作者/机构/期刊/引用数。
- 不要因为“标题相似”就标相关；要看技术领域、应用场景、TRL、合作模式是否兼容。
- 模拟需求已在 `demand_title` 中标明；标注时按正常需求处理，不因“模拟”降分。
- `q20` 是电网储能钠电材料；消费电子高电压钴酸锂是 `dem_020` 的配对需求，两者不要混。
- 全量模板的候选来自 300 条成果。若某 query 确实没有相关候选，在 `notes` 记录原因，评测时将该 query 单列，不强行凑 5 条相关。
