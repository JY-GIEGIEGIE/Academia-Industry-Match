# scripts/data

本目录包含数据采集、清洗、种子生成、抽取、导入和核验脚本，支持 v0.1 薄切片与全量数据。运行参数与依赖见各节说明。

## 1. 脚本一览

| 脚本 | 作用 | 主要输出 |
| --- | --- | --- |
| `config.py` | 子方向查询、关键词、评测 query、枚举映射 | 无 |
| `fetch_openalex.py` | 抓取 OpenAlex 原始快照 | `data/raw/openalex/<run_id>/*.json`、`data/manifests/fetch_openalex_*.json` |
| `build_thin_slice.py` | 摘要重建、清洗、去重、按子方向分层抽样 | `data/processed/achievements_clean_*.jsonl`、`data/samples/achievements_sample_*.jsonl` |
| `make_seed_data.py` | 生成薄切片种子，或与组内补充种子合并生成全量 | `data/samples/*_seed_v0.1.*` 或 `data/processed/{enterprises,demands}_v0.1.jsonl` |
| `make_eval_templates.py` | 生成 20 条检索 query + 50 对 pair 模板 | `data/eval/retrieval_queries_*.csv/.jsonl`、`data/eval/pair_labels_*.csv/.jsonl` |
| `validate_thin_slice.py` | 校验数量、字段、重复、模拟标记和全量来源追溯 | 终端报告 |
| `review_demands.py` | 只读核验指定私有交接目录的需求与企业 | 通过 `--output` 指定的统计 JSON；不修改输入 |

## 2. 运行顺序

下面命令都从仓库根目录执行，不依赖仓库外部的文件夹命名。如果只是启动前端演示，直接用仓库里的 fixtures 就行，不用重跑数据采集。

```bash
# 可选：提高 OpenAlex 配额
export OPENALEX_MAILTO="your-team@example.com"
export OPENALEX_API_KEY="..."   # https://openalex.org/settings/api

python scripts/data/fetch_openalex.py --run-id thin-20261117 --per-page 100
python scripts/data/build_thin_slice.py --run-id thin-20261117 --version v0.1-thin
python scripts/data/make_seed_data.py
python scripts/data/make_eval_templates.py --version v0.1-thin
python scripts/data/validate_thin_slice.py --version v0.1-thin
```

要核验组内 S-02 v0.1 全量需求时，运行：

```bash
python scripts/data/review_demands.py --data-root "/path/to/private-handoff" --output data/manifests/demands_review_checks_v0.1.json
```

`/path/to/private-handoff` 填自己解压交接包的路径，目录结构要求见[数据说明](../../data/README.md#私有交接数据与需求核验)。脚本只跑字段和统计检查，不能替代[报告](../../data/manifests/demands_review_v0.1.md)里的人工业务核验和来源核对。

## 3. 抓取参数

- **主查询**：每个子方向 1—4 条（薄切片阶段正极/负极多设几条以覆盖材料体系）；分 `relevance` 和 `recent` 两个视角，各取 100 条候选。
- **过滤条件**：`publication_year:2020-2026`、`has_abstract:true`、`type:article|review`。
- **请求控制**：间隔 0.6 秒；遇 429/5xx 退避重试；User-Agent 带上 `mailto`。
- **请求量**：薄切片大约 42 次请求；没配 key 时留意公共日配额。
- **重跑行为**：已存在的 raw 文件默认跳过，加 `--force` 才会重抓。重抓会覆盖同名 fetch manifest，要留旧统计需提前备份。

## 4. 清洗与抽样

- 用 OpenAlex `abstract_inverted_index` 还原摘要；
- 规范化标题、DOI、空白字符、HTML 标签和 Unicode；
- 按 DOI、OpenAlex ID、归一化标题去重；
- 用“上下文词 + 主题词 + 排除词”筛选领域相关论文；
- 按子方向配额抽样：6 个主方向 × 15 + 液流/超级电容 × 5 = 100；
- 每年最多 4 条，避免年份偏斜；
- 全量清洗集写 `data/processed/`（不入 git）；20 条截断样例写 `data/samples/`（入 git）。
- 全量使用 `v0.1`。`config.py` 为该版本增加专项查询，配额为 6 个主方向各 45 条、2 个辅助方向各 15 条。抽样先满足子方向，再按分数补足总数。
- 全量运行沿用“抓取 → 清洗 → 生成种子 → 校验”。这四步均选用 `v0.1`，本次抓取与清洗的运行标识为 `s02-v01`，每次请求上限 100 条，成果目标 300 条。生成全量种子使用组内交接包中的 `data/interim/seeds_v0.1.json`。
- 有组内快照时可直接开始清洗。全量来源校验要求保留 `data/raw/openalex/s02-v01/` 中的候选快照；公开仓库保留现有截断样例。

## 5. 数据政策

- 不抓 CNKI/万方，不绕过 CNIPA 反爬；arXiv 请求间隔 ≥3 秒。
- OpenAlex 元数据是 CC0，摘要版权可能归出版商；公开仓库只存正文 ≤600 字符的截断样例（末尾加省略号）。
- 需求与企业都是模拟数据，`is_simulated=true`，企业用化名。
- 完整数据、API key 和 `.env` 不进公开仓库。

## 6. 数据侧脚本

- `extract_labels.py`：Qwen 标签/TRL/指标抽取，JSON schema + 证据 + confidence；
- `embed.py`：Qwen `qwen3.7-text-embedding-flash` 1024 维向量化，`text_hash` 缓存；
- `load_db.py`：已提供（见第 8 节），已在 PostgreSQL 16.16 + pgvector 0.8.7 上验证 300 条全量导入与重复导入；
- `evaluate.py`：Recall@10、Precision@5、nDCG@10、MRR；B0—B2 三组基线（BM25 / 纯向量 / 标签+向量），B2 使用任一 `tech_field` 命中，另输出 `B2-primary` 仅主标签消融；B3（LLM 精排）待匹配引擎就绪后补。默认写 `baseline_<version>_top10.csv` 和 `data/interim/eval_query_vectors_<version>.jsonl`，冻结 query 向量以保证复现。

## 7. 共享 API 客户端

`extract_labels.py`、`embed.py` 和 `evaluate.py` 统一调 `scripts/common/llm_client.py`，不要各自手写 HTTP 请求：

```python
from scripts.common.llm_client import chat_json, embed_texts, rerank

labels = chat_json(messages)
vectors = embed_texts(texts, text_type="document")   # 检索 query 用 "query"
hits = rerank(query, documents, top_n=10)
```

- 自动读 `.env` 中自己的百炼 key；
- embedding 按 `(model, dim, text_type, text_hash)` 缓存到 `data/interim/`，不重复计费；
- 调用开销写 `data/interim/api_usage.jsonl`；
- 自检：`python scripts/common/llm_client.py --check`；小样本：`--demo`。

## 8. 数据库迁移与导入（BE2）

前置：PostgreSQL 16 + pgvector 0.8.x；`pip install -r requirements.txt`（psycopg 3）。完整数据从群文件交接包解压到 `data/processed/`。

```bash
# 只校验文件，不连库（默认薄切片；加 --dataset-version v0.1 校验全量）
python scripts/data/load_db.py --check --dataset-version v0.1

# 空库一键迁移 + 全量导入（校验 zip 与 processed 文件的 SHA-256）
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate \
  --dataset-version v0.1 \
  --embedding-model-version qwen3.7-text-embedding-flash-1024-v1 \
  --zip "D:/path/to/S-02_v0.1_组内交接.zip"

# 只迁移，不导入
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate --migrate-only

# 小样本冒烟（必须指向空库/临时库；导入器会拒绝往已含其他 dataset_version 的库写入）
python scripts/data/load_db.py --dsn "$SMOKE_DSN" --migrate --limit 20 --skip-hash

# 薄切片（100 成果 / 20 需求 / 10 企业；用独立的空库，不能写到全量库）
python scripts/data/load_db.py --dsn "$THIN_DSN" --migrate \
  --dataset-version v0.1-thin \
  --zip "D:/path/to/数据侧交接_v0.1-thin_2026-11-18_v3.zip"

# 标签 / 抽取 / 能力画像（全量；文件格式见 docs/09-项目管理/标签与画像文件格式_2026-11-19.md）
# --migrate 同时应用 0002 的 review_status 约束；已有库重复执行安全
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate \
  --dataset-version v0.1 \
  --embedding-model-version qwen3.7-text-embedding-flash-1024-v1 \
  --labeled data/processed/achievements_labeled_v0.1.jsonl \
  --profiles data/processed/capability_profiles_v0.1.jsonl
```

`--dataset-version` 会同时切换成果、标签、画像、向量、需求、企业、评测（query / pair）和哈希清单的默认路径。全量清单 `private_data_v0.1.json` 已就位，不需要再传 `--skip-hash`。`--queries` / `--pairs` 同时接受 JSONL 和 `make_eval_templates.py` 生成的 CSV；CSV 的候选 ID 用分号分隔，pair 的 `relevance_grade` 会转成整数。

`demand_tag` 由 `demand.tech_fields` / `application_scenarios` / `cooperation_modes` 在导入时确定性派生：`method=rule`、`confidence=1.0`、`evidence=demand.<字段>`、`review_status=pending`，第一个 `tech_field` 为 primary；`demand` 三个 JSONB 数组保留为 API 展示缓存。

导入默认拒绝往已有其他 `dataset_version` 的库写入。从薄切片升级到全量时加 `--allow-mixed-versions`；其余情况请用空库或临时库。

输出：`data/manifests/import_v0.1.json`、`data/manifests/load_report_v0.1.md`（运行时生成，每次覆盖，不入库）。连续执行两次导入即可验证幂等（`ON CONFLICT` 更新，不新增重复行）。

验证记录（2026-11-20，psycopg 3.3.9 + Docker PostgreSQL 16.16 + pgvector 0.8.7）：空库（public 0 表）一键迁移成功；导入 300 成果 / 100 需求 / 25 企业 / 20 query / 50 pair；连续三次导入数量不变，重复 DOI 0、孤儿向量 0、外键 0、`vector(1024)` 正常；主库从薄切片 100/20/10 覆盖到全量 300/100/25，`v0.1-thin` 残留 0；zip 与 processed 文件的 SHA-256 与 `private_data_v0.1.json` 一致。薄切片记录见 `docs/09-项目管理/BE2验收记录_v0.1-thin_2026-11-19.md`。

标签、抽取、画像已支持导入（`--labeled` / `--profiles`）。标签 code 按 `taxonomy_v0.1.md` 校验；每个成果最多 2 个 `tech_field`、恰好 1 个 `is_primary`。没有 `tech_field` 标签只警告（覆盖率问题）；有 `tech_field` 但缺主标签、多个主标签或超过 2 个 `tech_field` 直接报错；重跑会先删除该批成果的旧标签/抽取/画像再重建，避免主标签唯一索引冲突。`match_score` 表已建好，导入留给匹配引擎。
