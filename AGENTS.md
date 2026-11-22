# AGENTS.md — 数据侧第一次冲刺（截止 2026-11-22）

> 冲刺：第一次冲刺（First Sprint）
> 截止：2026-11-22
> 数据版本：v0.1-thin（当前 100 条薄切片）；本次冲刺扩量后的全量产物用 v0.1
> 适用：接手数据侧工作的同学及其 AI Agent
> 执行依据：`docs/09-项目管理/数据侧分工安排.md`

## 0. 先做什么

1. 读本文件。
2. 读 `data/spec/data_contract_v0.1.md`、`data/spec/taxonomy_v0.1.md`、`data/spec/eval_spec_v0.1.md`。
3. 读 `data/README.md`、`scripts/data/README.md`。
4. 确认自己接的是哪几项（第 2 节）。
5. 检查环境（第 4 节）；缺任何一项，停下来问贾越，不要自己 mock。

## 1. 当前数据状态

- 100 条成果薄切片已清洗；完整集在组内私有交接包的 `data/processed/achievements_clean_v0.1-thin.jsonl`（仓库不入库）。接收者自行选择解压目录，取得方式与路径规则见仓库内 `data/README.md`，不依赖提交者本机目录。
- 仓库 `data/samples/` 只有 20 条截断样例；**不要以为仓库里有完整数据**。
- 20 条需求、10 家企业、20 条 query、50 对 pair 模板已有；query/pair 标注为空。
- 没有 `extract_labels.py`、`embed.py`、`load_db.py`、`evaluate.py`；没有数据库。
- 100 条只是薄切片，不是最终 300—400 条。

## 2. 角色与任务

### 黄欣悦（DE，主接）

- 扩到 300—400 条成果；100 条需求 / 25 家企业；质量报告与交接。
- 用 `scripts/data/fetch_openalex.py`、`build_thin_slice.py` 扩量；先扩 `config.py` 的 `SUBFIELD_SPECS[*]["queries"]` 和每子方向 `target`（当前是薄切片 15/5），再传 `--target-total 300`，否则只会在 100 条基础上补分，子方向分布会偏；不要改 taxonomy。
- 输出：`data/processed/achievements_clean_v0.1.jsonl`；`data/processed/demands_v0.1.jsonl`；`data/processed/enterprises_v0.1.jsonl`；质量报告。仓库 `data/samples/` 只保留 20 条成果 + 20 条需求 + 10 家企业的可入库样例。
- 验收：300—400 条；6+2 子方向；必填 ≥95%；重复 <2%；来源 100%；100 需求/25 企业；全部 `is_simulated=true`。

### 陈镇灏（AI）

- 写 `scripts/data/extract_labels.py`：先 30 条校准，再全量抽取 + 10% 抽检。
- 写 `scripts/data/embed.py`：成果 + 需求向量化；1024 维；记录 model/version/text_hash。
- 抽取/向量/评测统一使用 `scripts/common/llm_client.py`（重试/批量/缓存/usage），不要各自写 HTTP。
- 写 `scripts/data/evaluate.py`：BM25 / 纯向量 / 标签+向量 三组基线（B0—B2）；B3（标签+向量+LLM 精排）待匹配引擎就绪后补；Recall@10、Precision@5、nDCG@10。
- 20 条 query + 50 对 pair 人工标注（与黄欣悦、贾越）。
- 输出：`data/processed/achievements_labeled_v0.1.jsonl`（薄切片试跑用 `_v0.1-thin`）；`data/processed/capability_profiles_v0.1.jsonl`；`data/processed/embeddings_v0.1.jsonl`；`data/manifests/baseline_v0.1.md`。
- 验收：标签覆盖 ≥95%；抽检 ≥90%；TRL 证据 100%；向量覆盖 100%；B0—B2 基线指标可复现。

### 张小桐（BE2）

- `migrations/`：PostgreSQL 16 + pgvector 0.8.x 表结构、迁移、索引。
- `scripts/data/load_db.py`：全量导入、幂等、一致性检查。
- 输出：`migrations/`；import manifest；一致性报告。
- 验收：空库一键迁移；`vector(1024)`；连续两次导入不重复；外键违规 0。

### 朱柔璇（BE1）

- 数据 API 字段契约：成果、需求、标签、匹配结果；与 DE/AI/BE2 对齐。
- 输出：`docs/02-需求分析/数据API契约_v0.1.md`（或等效文件）。
- 验收：字段与 `data_contract_v0.1.md` 一致；分页/过滤/错误码明确。

### 彭逸涵（FE）

- 帮黄欣悦写 20—30 条需求；用 20 条 mock 跑通推荐/详情页字段。
- 输出：需求文本；mock 页面。
- 验收：字段与 API 契约一致；模拟标记；可演示。

### 贾越（PM）

- 百炼 API key、PostgreSQL + pgvector、Embedding 方案；数据侧验收。
- 缺环境 = 阻塞，先解决再开工。

## 3. 依赖顺序（不要乱序）

1. 贾越环境就绪 + 黄欣悦契约冻结。
2. 黄欣悦扩量（300—400 / 100 / 25）。
3. 陈镇灏抽取：先用 100 条薄切片跑通，再上全量。
4. 陈镇灏画像 → 向量。
5. 张小桐建表（可与 3/4 并行）→ 导入（等向量）。
6. 陈镇灏评测（等向量 + 入库 + 标注）。
7. 黄欣悦质量/交接 → 贾越验收。
并行：朱柔璇 API 字段、彭逸涵需求/前端 mock。

## 4. 环境前置

- Python 3.11。
- OpenAlex 网络；可选 `OPENALEX_MAILTO` / `OPENALEX_API_KEY`。
- 百炼 Qwen API key（每人独立 key，只放本地 `.env`）。
- PostgreSQL 16 + pgvector 0.8.x。
- Qwen embedding 1024（本冲刺统一 `qwen3.7-text-embedding-flash`；BGE-M3 为备选，不得混用）。
- 缺任何一项，停下来问贾越，不要自己 mock 数据或改口径。

## 5. 不能做什么

- 不改 taxonomy 枚举/数据契约字段；确需改，先问 DE/AI/BE2。
- 不把 `data/raw/`、`data/processed/`、完整摘要、模型权重提交到公开仓库。
- 不提交 `.env`、API key、密码。
- 不重写已有 `fetch_openalex.py`、`build_thin_slice.py`、`make_seed_data.py`、`make_eval_templates.py`；需要时扩展。
- 不编造标签/TRL/IP/性能指标；无证据写 `unknown`。
- 不跳过校验；不把“本地跑过”当证据。

## 6. 验收命令

```bash
python -m compileall -q scripts
python scripts/data/validate_thin_slice.py --version v0.1-thin
```

新增脚本后自行补 pytest/校验，并在 PR/交接里写命令和结果。`validate_thin_slice.py` 只覆盖 100 条薄切片；扩到 300—400 条后必须扩展校验（数量、6+2 子方向、100 需求、25 企业、模拟标记）。

## 7. 交付格式

每个任务交：输出路径 + 命令/结果 + manifest/日志/报告 + 版本字段（`dataset_version`、`taxonomy_version`、`embedding_model_version`）。

第一次冲刺的所有产出标注 `sprint: 2026-11-22`。
