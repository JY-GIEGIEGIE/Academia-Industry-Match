# v0.1 最终质量报告（S-08 只读收口）

> 日期：2026-11-23
> 口径：S-05 已验收数据库与 S-04/S-09 冻结报告
> 原则：**本轮不修改 `data/processed/`、不写 PostgreSQL、不修改 S-04/S-05 历史验收记录。**

## 1. 数据规模与状态

| 项目 | 数量/结果 |
| --- | ---: |
| 成果 | 300 |
| 需求 | 100 |
| 企业 | 25 |
| `achievement_tag` | 1268（tech_field 403 / application_scenario 565 / cooperation_mode 300） |
| `achievement_extraction` | 300 |
| `achievement_text` / 画像 | 300 |
| `embedding` | 400（300 成果 + 100 需求） |
| `eval_query` / `eval_label` | 20 / 50 |
| `demand_tag` | 307（101 / 100 / 106；100 条 primary） |
| 有 primary `tech_field` 的成果 | 299 / 300（99.7%） |
| 非空 TRL 带 `trl_evidence` | 242 / 242 |
| `embedding_text_hash_mismatch` | 0 |
| 孤儿向量 | 0 |

S-05 验收状态保持不变：`achievement_tag=1268`、`needs_review=79`、`embedding=400`（S-05 验收时 118 tests；S-08 分支新增分析测试后 122 tests）。
S-08 本轮没有向数据库写入任何行，也没有重跑 `load_db`。

## 2. 评测结果

### 2.1 S-04 正式基线（保留，不重写）

| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR |
| --- | ---: | ---: | ---: | ---: |
| B0 | 0.861 | 0.610 | 0.757 | 0.758 |
| B1 | 0.897 | 0.770 | 0.852 | 0.912 |
| B2（主标签） | 0.892 | 0.740 | 0.836 | 0.912 |

B0 的 Precision@5 = 0.610，低于 eval spec 的 0.70；作为基线事实保留。

### 2.2 S-08 补充敏感性：B2-any

同一批 20 query、同一套 300 条成果向量、同一份冻结 query 向量（`data/interim/s04_eval_query_vectors_v0.1.jsonl`，sha256 `46fba251...`）：

| 基线 | Recall@10 | Precision@5 | nDCG@10 | MRR |
| --- | ---: | ---: | ---: | ---: |
| B0 | 0.861 | 0.610 | 0.757 | 0.758 |
| B1 | 0.897 | 0.760 | 0.852 | 0.912 |
| B2-any（任一 tech_field） | **0.911** | **0.770** | **0.861** | 0.912 |
| B2-primary（仅主标签） | 0.892 | 0.740 | 0.836 | 0.912 |

说明：

- B2-any 是补充敏感性口径，**不替代** S-04 的正式 B2 报告，也不改 eval spec。
- B2-any 相对 B2-primary 提升主要来自“多标签成果只要任一目标领域命中即可进入向量排序”。
- B1 的 Precision@5 从 S-04 的 0.770 变为 0.760，原因是本次使用冻结 query 向量；不隐藏该差异。
- 完整报告：`data/manifests/baseline_v0.1_s08_addendum.md`。
- Top-10 明细：`data/manifests/baseline_v0.1_top10.csv`（800 行）。
- 错误分析：`data/manifests/error_analysis_v0.1.md` / `.csv`（5 假阳 + 5 假阴；B2-any 补充口径）。

## 3. `needs_review` 与拟修正项

### 3.1 当前 79 条 `needs_review`

处置台账：`data/manifests/needs_review_disposition_v0.1.csv`。

- 79 条全部保留在库中，不丢弃、不改状态；S-08 结论为 `keep_needs_review_no_db_change`。
- 画像超过 250 字：74 条（251—305 字）。
- TRL=null：58 条；非空 TRL 242/242 有 `trl_evidence`。
- 无 primary `tech_field`：1 条 `ach_openalex_W4401101842`。
- 其余为 profile/TRL 组合或 LLM 待复核标记；逐条见 CSV。

### 3.2 拟修正但**未应用**的 50 条

清单：`data/manifests/proposed_data_corrections_v0.1.csv`。

- `ach_openalex_W4401101842`：建议补 `tech_field=electrolyte`（primary）；当前 tags 为空。
- 49 条 TRL=null 且 `review_status=pending`：建议规范为 `needs_review`。
- 以上均标记 `applied=false`、`requires_versioning=true`。

**为什么不直接改：** `achievement_tag`、`achievement_extraction`、`achievement_text`、`demand_tag` 没有 `dataset_version` 列；`load_db` 按 `achievement_id` 先删后插。直接改库或重导 `v0.1` 会原地改变 S-05 已验收的 1268/79 状态，且无法保留旧版本。若要应用，必须走 `v0.1.1` + 新库/新版本重新验收，不能打补丁。

## 4. 已知例外（不返工）

| 例外 | 现状 | 处置 |
| --- | --- | --- |
| 画像超长 | 74 条，251—305 字 | 保留原文；不重算 embedding |
| TRL=null | 58 条 | 保留 null；不编造；前端/API 显示“待确认” |
| 无 primary tech_field | 1 条 | 覆盖率仍 299/300（≥95%） |
| S-09 pair kappa | 二次 0.5714（n=10） | PM 已接受为例外；不重标 |
| S-07 需求问题 | 7 条 P1 + 50 处 datetime | 保留原 demands；交后续版本处理 |
| B0 Precision@5 | 0.610 < 0.70 | 作为基线事实保留 |

## 5. 复现信息

- `data/manifests/s08_analysis_summary_v0.1.json`：输入 SHA-256、指标、行数、query 向量 SHA。
- 脚本：`scripts/data/s08_analysis.py`（只读；不写 DB、不改 processed）。
- S-08 记录：`docs/09-项目管理/S-08_质量与评测收口记录_2026-11-23.md`。

## 6. 未完成项

- **30 条标签评测 + 20 条 TRL 边界评测**：当前没有独立 ground truth，不能用 S-03 的 30 条抽检 Y/N 代替；本轮不伪造指标，留作 S-08 后续人工评测。
- B2-any 若被 PM 定为正式口径，需要单独更新 eval spec、正式 baseline 和错误分析；当前只作为补充敏感性。
- 数据修正 50 条未应用；如需应用，走 `v0.1.1` 版本化流程。
- 发布 tag/release notes 待上述口径确定后由 S-08 完成。
