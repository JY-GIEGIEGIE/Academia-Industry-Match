# BE2 验收记录：数据库迁移与导入（v0.1-thin）

> 日期：2026-11-19
> 验收人：张小桐（BE2）
> 环境：Windows 11 / Python 3.12.6（`.venv`）/ Docker（WSL2 daemon）/ PostgreSQL 16.16 + pgvector 0.8.7
> 关联：`migrations/0001_init.sql`、`scripts/data/load_db.py`、`docs/09-项目管理/数据侧分工安排.md`
> 状态：v0.1-thin 通过；v0.1 全量已于 2026-11-20 复验，见 `BE2验收记录_v0.1_2026-11-20.md`

## 1. 结论

第一次冲刺的四条验收标准，在 v0.1-thin（100 成果 / 20 需求 / 10 企业 / 20 query / 50 pair）上全部通过：

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 空库一键迁移 | 通过 | 新建库 public 0 表 → `--migrate-only` 后 14 表、49 索引、74 约束 |
| `vector(1024)` | 通过 | `format_type` 返回 `vector(1024)`，HNSW 索引 `ix_embedding_vector_hnsw` |
| 连续两次导入不重复 | 通过 | 两次导入后 100/20/10/20/50 完全不变 |
| 外键违规 0 | 通过 | `fk_demand_enterprise`、`fk_eval_label_achievement`、`fk_eval_label_demand` 均为 0 |

附加验证：向量写入与距离查询、标签/抽取/画像导入、`--limit` 冒烟、交接包 SHA-256 校验、29 个单元测试。

## 2. 环境

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| PostgreSQL | 16.16（Debian） | `docker compose` 的 `db` 服务，容器 `aim-pgvector` |
| pgvector | 0.8.7 | 满足 0.8.x 要求 |
| 宿主端口 | 5433 | 本机 5432 被 PostgreSQL 17 占用；`环境与密钥共享方案.md` §4.1 允许改 5433 |
| Python | 3.12.6 | `.venv` 由 `D:\Python\python.exe -m venv` 创建 |
| 驱动 | psycopg 3.3.9 | 与 `requirements.txt` 一致 |
| Docker | WSL2 daemon 29.1.3 | Windows Docker Desktop 当时未启动，改用 WSL 内的 daemon；镜像与 compose 文件相同 |

## 3. 验收命令

以下命令在激活 `.venv` 后执行（`.venv\Scripts\activate`，或直接调用 `.venv/Scripts/python.exe`）。

```bash
# 1) 空库迁移（新库 be2_acceptance，public 0 表）
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate --migrate-only

# 2) 第一次导入（校验交接包与 processed 文件的 SHA-256）
python scripts/data/load_db.py --dsn "$DATABASE_URL" \
  --manifest data/manifests/private_data_v0.1-thin.json \
  --zip "D:/path/to/数据侧交接_v0.1-thin_2026-11-18_v3.zip"

# 3) 第二次导入（验证幂等）
python scripts/data/load_db.py --dsn "$DATABASE_URL" \
  --manifest data/manifests/private_data_v0.1-thin.json \
  --zip "D:/path/to/数据侧交接_v0.1-thin_2026-11-18_v3.zip"
```

## 4. 验收输出

迁移：

```text
Applying migrations
  migration: 0001_init.sql
  migrations applied
```

第一次导入：

```text
  server: PostgreSQL 16.16 (Debian 16.16-1.pgdg12+1) / pgvector 0.8.7
Importing
  imported: {'enterprise': 10, 'achievement': 100, 'demand': 20, 'embedding': 0, 'eval_query': 20, 'eval_label': 50}
  status: success
```

第二次导入：

```text
  imported: {'enterprise': 10, 'achievement': 100, 'demand': 20, 'embedding': 0, 'eval_query': 20, 'eval_label': 50}
  status: success
```

## 5. 数据库核对

```sql
SELECT 'achievement' t, count(*) FROM achievement UNION ALL
SELECT 'demand', count(*) FROM demand UNION ALL
SELECT 'enterprise', count(*) FROM enterprise UNION ALL
SELECT 'eval_query', count(*) FROM eval_query UNION ALL
SELECT 'eval_label', count(*) FROM eval_label ORDER BY 1;
```

```text
   t        | count
------------+-------
 achievement |   100
 demand      |    20
 enterprise  |    10
 eval_label  |    50
 eval_query  |    20
```

结构与索引：

```text
tables: 14  indexes: 49  constraints: 74
vector column: vector(1024)
hnsw index: ix_embedding_vector_hnsw
```

## 6. 一致性检查

来自 `data/manifests/load_report_v0.1.md`：

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
| `achievements_without_primary_tech_field` | 100 | INFO（标签未产出） |
| `achievements_without_profile` | 100 | INFO（画像未产出） |
| `achievements_without_embedding` | 100 | INFO（向量未产出） |
| `demands_without_embedding` | 20 | INFO（向量未产出） |
| `embedding_text_hash_mismatch` | 0 | INFO（无向量可比） |

`pipeline_run` 与 `dataset_manifest` 各 2 条，是本次新建验收库上两次运行的记录，不是数据重复；换库或多次重跑会累加。

`status` 只反映导入完整性和 8 项硬检查（重复 DOI、孤儿向量、维度、外键、模拟标记），**不包含向量、标签、画像的覆盖率**——覆盖率单独列在上面的 INFO 行里。所以薄切片在没有向量/标签/画像文件时也会显示 `success`，这只表示已导入的部分一致。

## 7. 扩展验证

| 项目 | 方法 | 结果 |
| --- | --- | --- |
| 向量写入 | 构造 1 条 1024 维测试向量，`--embeddings` 导入 | 成功，`vector_dims=1024`，自距离 0.000000 |
| 标签/抽取/画像 | 构造 3 条成果的 tags + extraction + profile | 6 标签 / 3 抽取 / 3 画像入库，ID 规则正确 |
| 标签变更 | 主标签 `electrolyte` 改为 `separator` 后重跑 | 旧行被替换，主标签正确，无残留 |
| 小样本 | `--limit 20` 在临时库 | 20 成果 / 20 需求 / 10 企业，eval 跳过，`success` |
| 哈希校验 | `--manifest` + `--zip` | zip 与两个 processed 文件 SHA-256 全部匹配 |
| 单元测试 | `python -m unittest discover -s tests -t .` | 32 个通过（无 psycopg 的解释器也通过） |

测试向量与构造标签在验证后已删除，验收库 `be2_acceptance` 已 drop，主库回到 100/20/10/20/50 的干净状态。

## 8. 幂等与替换语义

- 成果、需求、企业、向量、评测：`ON CONFLICT ... DO UPDATE`，重复导入行数不变。
- 标签/抽取/画像：先删除本批成果的旧记录再插入。原因是 `achievement_tag` 有部分唯一索引 `ux_achievement_tag_primary`（每个成果最多一个主 `tech_field`），只做 upsert 在标签 code 变更时会撞索引。
- `pipeline_run` / `dataset_manifest` 每次运行新增一条，属于运行历史，不参与重复率统计。

## 9. 未完成项（等数据）

| 项 | 等待文件 | 到位后动作 |
| --- | --- | --- |
| 向量覆盖率 100% | `embeddings_v0.1.jsonl`（陈镇灏） | `--embeddings` 导入，检查 `achievements_without_profile` 与 `rows_embedding` |
| 标签覆盖 ≥95% / TRL 证据 100% | `achievements_labeled_v0.1.jsonl`（陈镇灏） | `--labeled` 导入，检查 `achievements_without_primary_tech_field` |
| 画像覆盖 | `capability_profiles_v0.1.jsonl`（陈镇灏） | `--profiles` 导入 |
| 300—400 条成果 / 100 需求 / 25 企业 | `achievements_clean_v0.1.jsonl`、`demands_v0.1.jsonl`、`enterprises_v0.1.jsonl`（黄欣悦） | `--dataset-version v0.1` 重跑 |

全量到位后用一条命令切换：

```bash
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate \
  --dataset-version v0.1 --skip-hash
```

`--dataset-version v0.1` 会同时把六个默认路径切到全量：成果、标签、画像、向量在 `data/processed/`，需求和企业也从 `data/samples/*_seed.jsonl` 换成 `data/processed/demands_v0.1.jsonl`、`enterprises_v0.1.jsonl`（thin 是 20 需求 / 10 企业，全量是 100 / 25）。

（`--skip-hash` 因为 `private_data_v0.1-thin.json` 记录的是 thin 包的哈希；全量包发布后应更新该 manifest。）

## 10. 与团队口径的偏差

| 偏差 | 原因 | 影响 |
| --- | --- | --- |
| 端口 5433 而非 5432 | 本机 5432 被 PostgreSQL 17 占用 | 文档 §4.1 允许；`.env` 已同步 `DATABASE_URL` |
| Docker 用 WSL2 daemon | Windows Docker Desktop 未启动 | 镜像、compose 文件、容器名一致，结果等价 |
| 镜像用本地 `0.8.7-pg16` 打 `pg16` 标签 | 拉取 `pg16` 时 registry TLS 超时 | 版本完全相同，未重新下载 |

## 11. 附录

- 导入报告：`data/manifests/load_report_v0.1.md`（运行时生成，每次覆盖，不入库；本文 §5—§6 摘录了当次结果）
- 导入清单：`data/manifests/import_v0.1.json`（运行时生成，含 run_id、数量、hash、版本、错误；不入库）
- 私有数据哈希：`data/manifests/private_data_v0.1-thin.json`
- 表结构：`migrations/0001_init.sql`
- 导入脚本：`scripts/data/load_db.py`
- 单元测试：`tests/test_load_db.py`
- 格式约定：`docs/09-项目管理/embedding_text_type口径_2026-11-19.md`、`docs/09-项目管理/标签与画像文件格式_2026-11-19.md`
