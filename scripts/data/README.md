# scripts/data

数据采集、清洗、种子与评测模板脚本。设计目标是**无第三方依赖、可重跑、每步留痕**，先支撑 v0.1 薄切片，再扩展到全量。

## 1. 脚本

| 脚本 | 作用 | 主要输出 |
| --- | --- | --- |
| `config.py` | 子方向查询、关键词、评测 query、枚举映射 | 无 |
| `fetch_openalex.py` | 抓取 OpenAlex 原始快照 | `data/raw/openalex/<run_id>/*.json`、`data/manifests/fetch_openalex_*.json` |
| `build_thin_slice.py` | 摘要重建、清洗、去重、按子方向分层抽样 | `data/processed/achievements_clean_*.jsonl`、`data/samples/achievements_sample_*.jsonl` |
| `make_seed_data.py` | 生成 10 家企业 + 20 条模拟需求 | `data/samples/enterprises_seed_v0.1.jsonl/.csv`、`data/samples/demands_seed_v0.1.jsonl/.csv` |
| `make_eval_templates.py` | 生成 20 条检索 query + 50 对 pair 模板 | `data/eval/retrieval_queries_*.csv/.jsonl`、`data/eval/pair_labels_*.csv/.jsonl` |
| `validate_thin_slice.py` | 校验薄切片数量/字段/模拟标记 | 终端报告 |

## 2. 运行顺序

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

## 3. 抓取参数

- **主查询**：每个子方向 1—4 条（薄切片阶段，正极/负极多几条以覆盖材料体系）；`relevance` + `recent` 两个视角，各 100 条候选。
- **过滤**：`publication_year:2020-2026`、`has_abstract:true`、`type:article|review`。
- **礼貌**：请求间隔 0.6 秒；429/5xx 退避重试；`mailto` 加入 User-Agent。
- **请求量**：薄切片约 42 次请求；无 key 时注意共享日预算。
- **可重跑**：已有 raw 文件默认跳过；`--force` 重抓。注意重跑会覆盖同名 fetch manifest，原始运行统计需另存。

## 4. 清洗与抽样

- 从 OpenAlex `abstract_inverted_index` 重建摘要；
- 规范化标题/DOI/空白/HTML/Unicode；
- 按 DOI、OpenAlex ID、归一化标题去重；
- 用“上下文词 + 主题词 + 排除词”过滤领域相关；
- 按子方向配额抽样：6 个主方向 × 15 + 液流/超级电容 × 5 = 100；
- 每年最多 4 条，避免年份偏斜；
- 全量清洗集写 `data/processed/`（不入 git）；20 条截断样例写 `data/samples/`（入 git）。
- 扩到 300—400 条时，先扩充 `config.py` 的 `SUBFIELD_SPECS[*]["queries"]` 和每子方向 `target`（当前是薄切片 15/5），再传 `--target-total 300` 以上；只改总目标数会从剩余池按分数补足，子方向分布会偏。

## 5. 数据政策

- 不抓 CNKI/万方；不绕过 CNIPA 反爬；arXiv 请求间隔 ≥3 秒。
- OpenAlex 元数据 CC0，摘要版权可能属于出版商；公开仓库只放正文 ≤600 字符的样例（截断时加省略号）。
- 需求/企业均为模拟数据，`is_simulated=true`；企业使用化名。
- 完整数据、API key、`.env` 不入公开仓库。

## 6. 下一步（尚未实现）

- `extract_labels.py`：Qwen 标签/TRL/指标抽取，JSON schema + 证据 + confidence；
- `embed.py`：Qwen `qwen3.7-text-embedding-flash` 1024 维向量化，`text_hash` 缓存；
- `load_db.py`：已提供（见第 8 节），已在 PostgreSQL 16.16 + pgvector 0.8.7 上验证 100 条导入与重复导入；
- `evaluate.py`：Recall@10、Precision@5、nDCG@10；本冲刺先做 B0—B2 三组基线（BM25 / 纯向量 / 标签+向量），B3（LLM 精排）待匹配引擎就绪后补。

## 7. 共享 API 客户端

`extract_labels.py` / `embed.py` / `evaluate.py` 统一使用 `scripts/common/llm_client.py`，不要各自写 HTTP：

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
# 只校验文件，不连库
python scripts/data/load_db.py --check

# 空库一键迁移 + 导入（先校验 zip / processed 的 SHA-256）
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate \
  --manifest data/manifests/private_data_v0.1-thin.json \
  --zip "D:/path/to/数据侧交接_v0.1-thin_2026-11-18_v3.zip"

# 只迁移，不导入
python scripts/data/load_db.py --dsn "$DATABASE_URL" --migrate --migrate-only

# 小样本冒烟（跳过 eval，避免外键不完整）
python scripts/data/load_db.py --dsn "$DATABASE_URL" --limit 20 --skip-hash
```

输出：`data/manifests/import_v0.1.json`、`data/manifests/load_report_v0.1.md`。连续执行两次导入即可验证幂等（`ON CONFLICT` 更新，不新增重复行）。

验证记录（2026-11-19，psycopg 3.3.4 + Docker PostgreSQL 16.16 + pgvector 0.8.7）：空库（public 0 表）一键迁移成功；导入 100 成果 / 20 需求 / 10 企业 / 20 query / 50 pair；连续导入后数量不变，重复 DOI 0、孤儿向量 0、外键 0、`vector(1024)` 正常；测试向量导入与距离查询通过后已清理；`--limit 20` 冒烟通过；zip 与 processed 文件的 SHA-256 与 manifest 一致。

标签/画像/TRL（`achievement_tag`、`achievement_text`、`achievement_extraction`）和 `match_score` 表已建好；等陈镇灏/匹配引擎产出 JSONL 后再补导入。本次骨架只覆盖成果、需求、企业、向量和评测。
