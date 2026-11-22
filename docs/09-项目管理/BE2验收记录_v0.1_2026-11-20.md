# BE2 验收记录：数据库迁移与导入（v0.1）

> 日期：2026-11-20
> 验收人：张小桐（BE2，S-05）
> 环境：Windows 11 / Python 3.12.6（`.venv`）/ Docker Desktop 29.7.2 / PostgreSQL 16.16 + pgvector 0.8.7
> 关联：`migrations/0001_init.sql`、`scripts/data/load_db.py`、`data/manifests/private_data_v0.1.json`
> 状态：v0.1 全量通过；向量、标签、画像文件到位后补覆盖率

## 1. 结论

S-02 交接的 v0.1 全量数据（300 成果 / 100 需求 / 25 企业 / 20 query / 50 pair）在**空验收库**和**主库**上都通过：

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 空库一键迁移 | 通过 | `s05_v01_accept` 从 0 表到 14 表、49 索引、74 约束 |
| `vector(1024)` | 通过 | `format_type` 返回 `vector(1024)`，HNSW 索引 `ix_embedding_vector_hnsw` |
| 连续多次导入不重复 | 通过 | 验收库 3 次、主库 3 次，计数始终 300/100/25/20/50 |
| 外键违规 0 | 通过 | `fk_demand_enterprise`、`fk_eval_label_achievement`、`fk_eval_label_demand` 均为 0 |
| 全量替换薄切片 | 通过 | 主库 100/20/10 → 300/100/25，`v0.1-thin` 残留 0 条 |
| 交接包完整性 | 通过 | zip SHA-256 匹配；包内 `SHA256SUMS.txt` 88/88 |
| 模型版本落库 | 通过 | `dataset_manifest.embedding_model = qwen3.7-text-embedding-flash-1024-v1` |

## 2. 环境

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| PostgreSQL | 16.16（Debian） | 容器 `aim-pgvector`，`docker compose` 的 `db` 服务 |
| pgvector | 0.8.7 | 满足 0.8.x 要求 |
| 宿主端口 | 5433 | 本机 5432 被 PostgreSQL 17 占用；`环境与密钥共享方案.md` §4.1 允许改 5433 |
| Python | 3.12.6 | `.venv` |
| 驱动 | psycopg 3.3.9 | 与 `requirements.txt` 一致 |
| Docker | Desktop 29.7.2 | 容器 `aim-pgvector` 由 `docker start` 拉起 |

## 3. 数据源与完整性

| 项目 | 值 |
| --- | --- |
| 交接包 | `S-02_v0.1_组内交接.zip`（2026-11-20） |
| 包大小 | 10,469,610 字节 |
| 包 SHA-256 | `154dfe1c092c3540b705231e55219405ae449db2a1466b7b7153d24bf82364a5` |
| 包内校验 | `SHA256SUMS.txt` 88/88 匹配 |
| 成果 / 需求 / 企业 | 300 / 100 / 25 |
| 评测 | 20 query / 50 pair（`v0.1` 模板） |
| 重复（ID、DOI、源 ID、归一化标题） | 0 / 300 |
| 需求 → 企业外键缺失 | 0 / 100 |
| 与薄切片关系 | 薄切片 100 成果、20 需求、10 企业全部是全量子集 |

`data/manifests/private_data_v0.1.json` 记录 zip 与三份私有 processed 文件的哈希。评测模板已入库到 `data/eval/`，由 `.gitattributes` 统一为 LF，字节与包内 CRLF 不同，故清单不再重复列它们——包级 SHA-256 已覆盖。

## 4. 验收命令

```bash
# 1) 新建空验收库
docker exec aim-pgvector psql -U aim -d academia_industry_match -c "CREATE DATABASE s05_v01_accept"

# 2) 空库迁移 + 第一次全量导入（校验 zip 与私有文件哈希）
python scripts/data/load_db.py --dsn "${DATABASE_URL%/*}/s05_v01_accept" \
  --migrate --dataset-version v0.1 \
  --embedding-model-version qwen3.7-text-embedding-flash-1024-v1 \
  --zip "D:/path/to/S-02_v0.1_组内交接.zip" \
  --report data/manifests/load_report_v0.1_accept.md \
  --import-manifest data/manifests/import_v0.1_accept.json

# 3) 第二次、第三次导入（验幂等与模型版本落库）
python scripts/data/load_db.py --dsn "${DATABASE_URL%/*}/s05_v01_accept" \
  --dataset-version v0.1 \
  --embedding-model-version qwen3.7-text-embedding-flash-1024-v1 \
  --zip "D:/path/to/S-02_v0.1_组内交接.zip" \
  --report data/manifests/load_report_v0.1_accept.md \
  --import-manifest data/manifests/import_v0.1_accept.json

# 4) 主库覆盖（薄切片 → 全量；混版升级需显式开关）
python scripts/data/load_db.py --dsn "$DATABASE_URL" \
  --dataset-version v0.1 \
  --embedding-model-version qwen3.7-text-embedding-flash-1024-v1 \
  --allow-mixed-versions \
  --zip "D:/path/to/S-02_v0.1_组内交接.zip"
```

`--dataset-version v0.1` 会同时切换七类输入：成果、标签、画像、向量、需求、企业、评测（query / pair）与哈希清单。

## 5. 验收输出

迁移：

```text
Applying migrations
  migration: 0001_init.sql
  server: PostgreSQL 16.16 (Debian 16.16-1.pgdg12+1) / pgvector 0.8.7
```

验收库首次导入（`run_id: load-20261120T140341205249Z`）：

```text
  imported: {'enterprise': 25, 'achievement': 300, 'demand': 100, 'embedding': 0, 'eval_query': 20, 'eval_label': 50}
  status: success
```

主库最终导入（`run_id: load-20261120T140444088820Z`）：

```text
  imported: {'enterprise': 25, 'achievement': 300, 'demand': 100, 'embedding': 0, 'eval_query': 20, 'eval_label': 50}
  status: success
```

> 验收库共 3 次导入：前两次（`load-20261120T140341205249Z`、`load-20261120T140354352715Z`）未传 `--embedding-model-version`，`dataset_manifest.embedding_model` 为 NULL；第三次 `load-20261120T140443436901Z` 补传后写入 `qwen3.7-text-embedding-flash-1024-v1`。§4 的命令是最终口径。

## 6. 数据库核对

```text
 achievement |   300
 demand      |   100
 enterprise  |    25
 eval_query  |    20
 eval_label  |    50
 embedding   |     0
```

```text
tables: 14  indexes: 49  constraints: 74
vector column: vector(1024)
hnsw index: ix_embedding_vector_hnsw
achievement.dataset_version: v0.1 × 300（v0.1-thin 残留 0）
demand.dataset_version:      v0.1 × 100
```

## 7. 一致性检查

> 2026-11-22 补充：`load_db --check` 已支持 `--queries` / `--pairs` 直接读取 CSV；标签无 evidence 必须 `needs_review` 且 confidence ≤0.4；`key_metrics` 必须满足 `{name,value,unit,evidence}`；`demand_tag` 从 `demand` 三个结构化数组派生。对应测试已加入 `tests/test_load_db.py`。

来自 `data/manifests/load_report_v0.1.md`，2026-11-20 快照为 22 项 OK；2026-11-22 新增 `demands_without_tech_field` 后共 23 项：

| 检查 | 值 | 结果 |
| --- | ---: | --- |
| `duplicate_doi` | 0 | OK |
| `orphan_embeddings` | 0 | OK |
| `vector_dim_mismatch` | 0 | OK |
| `fk_demand_enterprise` | 0 | OK |
| `fk_eval_label_achievement` | 0 | OK |
| `fk_eval_label_demand` | 0 | OK |
| `simulated_demand_false` | 0 | OK |
| `simulated_enterprise_false` | 0 | OK |
| `demands_without_tech_field` | 0 | OK（100 条需求派生 307 条 demand_tag） |
| `achievements_without_primary_tech_field` | 300 | INFO（标签未产出） |
| `achievements_without_profile` | 300 | INFO（画像未产出） |
| `achievements_without_embedding` | 300 | INFO（向量未产出） |
| `demands_without_embedding` | 100 | INFO（向量未产出） |
| `embedding_text_hash_mismatch` | 0 | INFO（无向量可比） |

`status` 只反映导入完整性和 9 项硬检查（重复 DOI、孤儿向量、维度、外键、模拟标记、需求 tech_field 覆盖），**不包含向量、标签、画像覆盖率**；覆盖率单独列在 INFO 行。

## 8. 幂等与覆盖

- 验收库连续 3 次导入、主库连续 3 次导入，六张主表计数不变。
- 主库原有 100 条 `v0.1-thin` 成果被同 ID 的 `v0.1` 记录覆盖，新增 200 条；需求 20 → 100，企业 10 → 25。
- 导入器默认拒绝往已有其他 `dataset_version` 的库写入；本次薄切片 → 全量的升级发生在守卫加入前，现在重做同样的升级需加 `--allow-mixed-versions`。
- `pipeline_run` / `dataset_manifest` 每次运行新增一条：验收库 3 条，主库 8 条（5 次 thin 历史 + 3 次全量），属于运行历史，不是数据重复。
- 成果、需求、企业、评测、向量：`ON CONFLICT ... DO UPDATE`；标签/抽取/画像：先删本批旧记录再插入。

## 9. 本次修复的导入缺陷

| 缺陷 | 影响 | 修复 |
| --- | --- | --- |
| 评测路径不随 `--dataset-version` 切换 | 全量导入会用 thin 的 20 query / 50 pair，并把评测行标成 `v0.1-thin` | `queries`、`pairs` 纳入版本解析 |
| 哈希清单不随版本切换 | `--zip` 仍比 thin 包的哈希，全量包必然失败 | `manifest` 纳入版本解析，新增 `private_data_v0.1.json` |
| `embedding_model_version` 未传 | 前两次导入 `dataset_manifest.embedding_model` 为 NULL | 第三次补传 `qwen3.7-text-embedding-flash-1024-v1`，主库最终 run 有值 |
| 混版导入只拦 `--limit` | 薄切片命令可把全量库的成果和评测集静默改成 `v0.1-thin` | 所有导入默认拒绝混版；升级需 `--allow-mixed-versions` |

## 10. 未完成项

> 2026-11-22 更新：本节等待的三份 JSONL 与 20+50 标注均已到位，全量导入与覆盖率复验见 `BE2验收记录_v0.1_全量_2026-11-22.md`；本节保留为当时的待办记录。

| 项 | 等待文件 | 到位后动作 |
| --- | --- | --- |
| 向量覆盖率 100% | `embeddings_v0.1.jsonl`（陈镇灏） | `--embeddings` 导入，检查 `rows_embedding` 与 `achievements_without_embedding` |
| 标签覆盖 ≥95% / TRL 证据 100% | `achievements_labeled_v0.1.jsonl`（陈镇灏） | `--labeled` 导入，检查 `achievements_without_primary_tech_field` |
| 画像覆盖 | `capability_profiles_v0.1.jsonl`（陈镇灏） | `--profiles` 导入，检查 `achievements_without_profile` |
| 评测标注 | 20 query / 50 pair 的 `relevance_grade` | 标注完成后重导 `eval_query` / `eval_label` |

上述三份文件的导入路径已用合成数据在临时库预演：300 条标签行写入 900 条 tag / 300 条 extraction，300 条画像写入 300 条 text，400 条向量（300 成果 + 100 需求），二次导入按替换语义计数不变。真实文件到位后按 §4 的命令重跑即可。

## 11. 口径说明

- 25 条企业记录没有 `dataset_version` 字段，导入时按 `--dataset-version` 默认填 `v0.1`，只产生 warning。
- 成果文件多出 6 个构建字段（`query_lens`、`query_tag`、`query_tags`、`raw_payload_path`、`selection_hits`、`selection_score`），导入器按设计忽略。
- 300 条成果全部带 `abstract_reconstructed`，摘要来自 OpenAlex 倒排索引重构，不是原文；抽取阶段需知情。
- 1 条成果没有 DOI，1 家企业没有对应需求，均不违反约束。
- 评测模板当前全部未标注：`pair_labels` 的 `relevance_grade` 为空，`retrieval_queries` 的 `relevant_achievement_ids` 为空。

## 12. 附录

- 导入报告：`data/manifests/load_report_v0.1.md`（主库）、`data/manifests/load_report_v0.1_accept.md`（验收库）；运行时生成，每次覆盖，不入库
- 导入清单：`data/manifests/import_v0.1.json`、`data/manifests/import_v0.1_accept.json`；同上
- 私有数据哈希：`data/manifests/private_data_v0.1.json`
- 表结构：`migrations/0001_init.sql`、`migrations/0002_review_status_needs_review.sql`
- 导入脚本：`scripts/data/load_db.py`
- 单元测试：`tests/test_load_db.py`
- 薄切片记录：`docs/09-项目管理/BE2验收记录_v0.1-thin_2026-11-19.md`

## 13. 2026-11-21 口径同步（正式标签/画像文件导入前）

- `achievement_tag`、`achievement_extraction`、`demand_tag` 的 `review_status` 放开 `needs_review`，由 `migrations/0002_review_status_needs_review.sql` 完成；`needs_review` 记录仍入库。
- `load_db.py` 接受脚本生成的 `tag_id`、`extraction_id`、`text_id`（要求全局唯一、跨次运行稳定）；缺省时仍按原公式生成。
- `trl=null`、`key_metrics=[]`、画像缺失均不阻塞导入；覆盖率仍由 INFO 类检查报告，不作为导入失败条件。
- 单元测试全仓 54 条通过（load_db 46 条；新增 `needs_review`、脚本 ID、空 TRL/空指标、无证据标签、`key_metrics` 字段、CSV eval 输入、需求标签派生用例）。
- `demand_tag` 从 `demand` 三个结构化数组派生：100 条需求生成 307 行（101 tech_field / 100 application_scenario / 106 cooperation_mode），100 条 primary tech_field；`demand_tag` 覆盖检查已加入一致性报告。
