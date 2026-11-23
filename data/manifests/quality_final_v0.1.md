# 数据质量与最终处置（v0.1）

> 日期：2026-11-23  
> 范围：S-03 抽取产物 + S-04 评测数据 + S-09 冻结标注  
> 处置人：贾越（PM）

## 1. 数据规模

| 项目 | 数量 |
| --- | ---: |
| 成果 | 300 |
| 需求 | 100 |
| 企业 | 25 |
| `achievement_tag` | 1269 |
| `achievement_extraction` | 300 |
| `achievement_text` / 画像 | 300 |
| embedding | 400（300 成果 + 100 需求） |
| 检索 query | 20 |
| pair 标注 | 50 |

最终 `achievements_labeled_v0.1.jsonl` SHA-256：`fccbadf88d67872b5f41525d9bd584bea51621bde807b97c279c6f06451e30f8`。  
最终 `achievements_labeled` 中 `needs_review=128`（原 79 + 49 条 null TRL 从 pending 规范为 needs_review），`pending=172`。

## 2. 处置结果

| 类别 | 数量/结果 | 处置 |
| --- | --- | --- |
| 画像超过 250 字 | 74 条（251—305 字） | **接受长度例外**；保留原文，不重算向量；页面显示待复核 |
| TRL=null | 58 条 | 保留 null，不编造；`review_status=needs_review`；页面显示“TRL 待确认” |
| 无 tech_field | 1 条 `ach_openalex_W4401101842` | 已补 `electrolyte` 主标签和证据；`review_status` 保留 needs_review 待 S-08 签收 |
| 其他 needs_review | 4 条 | 保留 needs_review，逐条列入 `needs_review_disposition_v0.1.csv` |
| key_metrics / retry | 原分类 4/1 条 | 已在处置表中保留状态；不影响已有 embedding |

处置台账：`data/manifests/needs_review_disposition_v0.1.csv`。

本次没有改动任何画像文本、TRL 证据或 embedding；因此不需要重跑 400 条向量。如果后续修改画像或补 TRL，必须重跑对应 embedding 并更新哈希。

## 3. 导入校验

`load_db --check --dataset-version v0.1`：

- achievements 300 / demands 100 / enterprises 25
- embeddings 400 / queries 20 / pairs 50
- **errors 0；warnings 77**（74 条画像长度 + 其他非阻断提示）
- 无 `achievement` 缺 tech_field；无 embedding 维度或外键错误

## 4. 评测结果

最终 query 向量：`data/interim/eval_query_vectors_v0.1.jsonl`  
SHA-256：`b9d15953e2934a1550bbf3e74ef77cbefc2c29fc8ab982748937313ed66954e0`

| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR |
| --- | ---: | ---: | ---: | ---: |
| B0 | 0.861 | 0.610 | 0.757 | 0.758 |
| B1 | 0.897 | 0.760 | 0.852 | 0.912 |
| B2（任一 tech_field） | 0.906 | 0.770 | 0.858 | 0.912 |
| B2-primary（仅主标签消融） | 0.887 | 0.730 | 0.833 | 0.912 |

Top-10：`data/manifests/baseline_v0.1_top10.csv`  
错误分析：`data/manifests/error_analysis_v0.1.md` / `.csv`

## 5. S-09 标注例外

- query：线性 kappa 0.4653 / 二次 0.6321
- pair：线性 kappa 0.4828 / 二次 0.5714；pair 双标 n=10
- PM 决定：pair 二次加权 kappa 0.5714 接受为本次例外，不重标；正式评测集按冻结文件使用。

## 6. 已知限制

- 74 条画像长度例外是人工验收决定，不代表满足 150—250 的严格目标。
- 58 条 TRL=null 是未知而非 0；匹配时不得做硬过滤，前端显示待确认。
- B0 Precision@5 0.610 低于 0.70 目标，作为基线事实保留。
- 重新生成 query 向量会改变 B1/B2 和 Top-10；必须重新生成报告和错误分析，不能沿用旧明细。
- `achievements_labeled` 的 128 条 needs_review 不丢失；S-08 仍需做发布前最终签收。
