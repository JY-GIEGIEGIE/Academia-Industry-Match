# BE2 验收记录 v0.1（全量数据复验）

> 验收人：张小桐（BE2，S-05 建表与导入）
> 日期：2026-11-22
> 代码基线：main `cba15e7`（含 #5、#7、#10、#11、#12、#13、#14、#15）
> 数据包：`S-04_v0.1_2026-11-22_修订_corrected_2026-11-23.zip`
> 数据包 sha256：`a3394bf12cf2168e45214d15a7c2d2deab6b31bdb054fd0ed3d68666cb209af0`
> 环境：PostgreSQL 16.16 + pgvector 0.8.7，容器 `aim-pgvector`，`127.0.0.1:5433`
> 结论：**通过，保留已知限制**（限制见 §4，与 S-04 验收记录一致）

## 1. 交付包校验

| 检查 | 结果 |
| --- | --- |
| zip sha256 | 与交件人给的值一致 |
| 包内 `SHA256SUMS.txt` | **25/25 OK** |
| `data/eval/*` 与 `data/manifests/dataset_v0.1.json` | 与 main `cba15e7` **逐字节一致**；`dataset_v0.1.json` 为 `c5bd2569…`，`annotation_status=frozen` |
| 基础数据 | `achievements_clean` / `demands` / `enterprises` 与 S-02 包哈希一致，底稿未被改动 |
| `load_db --check --zip …` | **errors 0 / warnings 77** |

77 条 warning 的构成：74 条画像超过 250 字、1 条成果没有 `tech_field`、1 条 `achievements` 多余构建字段、1 条企业缺 `dataset_version` 的汇总提示（覆盖 25 行）。均为已知限制，不阻塞导入。

`data/manifests/private_data_v0.1.json` 已更新为 S-04 校正包，并登记 6 个私有文件的行数与哈希；`source_package` 保留 S-02 包信息。

## 2. 导入结果

验收库 `s05_v01_final_20261122` 与主库 `academia_industry_match` 均执行全量导入，并各重复一次验证幂等。

```bash
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate \
  --dataset-version v0.1 \
  --embedding-model-version qwen3.7-text-embedding-flash-1024-v1 \
  --zip "$HANDOFF_ZIP"
```

| 表 | 行数 | 说明 |
| --- | ---: | --- |
| `achievement` | 300 | |
| `demand` | 100 | |
| `enterprise` | 25 | |
| `achievement_tag` | 1268 | tech_field 403 / application_scenario 565 / cooperation_mode 300 |
| `achievement_extraction` | 300 | |
| `achievement_text` | 300 | 能力画像 |
| `embedding` | 400 | 300 成果 + 100 需求 |
| `demand_tag` | 307 | 101 tech_field / 100 application_scenario / 106 cooperation_mode；100 条 primary |
| `eval_query` | 20 | 20/20 有标注 |
| `eval_label` | 50 | 50/50 有 `relevance_grade` |

重复导入按替换语义执行（`replaced 1268 tag rows and 300 extraction rows`、`replaced 400 existing vectors`、`replaced 300 profile rows`），两次计数完全一致，无重复行。

## 3. 覆盖率验收

| 验收项 | 目标 | 实测 | 结果 |
| --- | --- | ---: | --- |
| 有主 `tech_field` 的成果 | ≥285 | 299 / 300（99.7%） | 通过 |
| 每个成果 `tech_field` 数 | ≤2 | 最大 2 | 通过 |
| 非空 TRL 带 `trl_evidence` | 100% | 242 / 242 | 通过 |
| 能力画像 | 300 | 300 / 300 | 通过 |
| 成果向量 | 300 | 300 / 300 | 通过 |
| 需求向量 | 100 | 100 / 100 | 通过 |
| 向量维度 | 1024 | 400 / 400 为 1024 | 通过 |
| `embedding_text_hash_mismatch` | 0 | 0 | 通过 |
| `orphan_embeddings` | 0 | 0 | 通过 |
| `achievements_without_embedding` | 0 | 0 | 通过 |
| `demands_without_embedding` | 0 | 0 | 通过 |
| `eval_query` 标注 | 20 | 20 | 通过 |
| `eval_label` 标注 | 50 | 50 | 通过 |
| `vector_dim_mismatch` | 0 | 0 | 通过 |
| `duplicate_doi` | 0 | 0 | 通过 |

其余一致性检查（`fk_demand_enterprise`、`fk_eval_label_*`、`simulated_*_false`、`demands_without_tech_field`）均为 0。

## 4. 已知限制（PM 已接受，不返工）

- **79 条 `needs_review`**：抽取记录标待复核，但全部入库、不丢弃；标签表本身 1268 条均有 evidence。
- **74 条画像超过 250 字**：范围 166—305 字，平均 232.7；保留原文，由 S-08 在质量报告处置。
- **58 条 `TRL=null`**：无中试/量产证据时按硬约束降级；非空 TRL 100% 有证据。
- **1 条成果无 `tech_field`**：`ach_openalex_W4401101842`，无主标签，满足 ≥285 的覆盖目标。
- **pair 二次加权 kappa 0.5714**：低于 0.6，PM 已决定作为 S-09 例外接受。
- **B0 Precision@5 = 0.610**：低于 eval spec 的 0.70，作为基线事实保留。

## 5. 代码与测试

- main `cba15e7` 上 `python -m unittest discover -s tests -t .`：**118 项通过**。
- `0001_init.sql` + `0002_review_status_needs_review.sql` 在空库和主库均成功应用。
- `demand_tag` 派生、CSV 评测输入、`needs_review` 四值、脚本生成 ID 均已包含在 main 中。

## 6. 证据文件（运行时生成，本地保留，不入库）

| 文件 | 用途 |
| --- | --- |
| `data/manifests/load_report_v0.1_final_accept.md` | 验收库导入报告 |
| `data/manifests/import_v0.1_final_accept.json` | 验收库导入清单 |
| `data/manifests/load_report_v0.1_final_main.md` | 主库导入报告 |
| `data/manifests/import_v0.1_final_main.json` | 主库导入清单 |
| `dataset_manifest` 表 | 记录 `embedding_model=qwen3.7-text-embedding-flash-1024-v1`、计数与 6 个文件哈希 |

## 7. 未纳入本次验收

- `raw_source_record` 仍为 0 行：v0.1 交接包未包含原始快照，表保持 schema-only；如需 DB 内追溯 raw，需要另立任务。
- `match_score` 为 0 行：匹配引擎属后续任务。
- S-08 的最终质量报告（Top-10 明细、假阳/假阴分析）不在 S-05 范围。

## 8. 结论

S-05 的建表与全量导入已完成并通过验收：数据结构、计数、覆盖率、向量口径与评测标注均符合 v0.1 约定；重复导入幂等；已知数据质量限制已记录并由 PM 接受。后续只需在 S-08 质量报告中引用本记录，不需要再改导入代码。
