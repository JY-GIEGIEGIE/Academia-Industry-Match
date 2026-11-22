# 数据目录

本目录存放「技术转化智能匹配与产学研对接系统」的数据、契约和样例。主源使用 **OpenAlex**，先跑通 100 条清洗薄切片和评测模板，再扩展到 300—400 条成果、100 条需求和 25 家企业画像。

## 1. 目录结构

```text
data/
├── README.md                 # 本文件
├── spec/                     # 数据契约、标签体系、评测规范（入库，长期维护）
├── samples/                  # 可入库的小样例（20 条成果、20 条需求、10 家企业画像）
├── eval/                     # 检索 query 与 pair 标注模板（入库）
├── manifests/                # 抓取/构建清单（入库）；导入运行日志除外
├── raw/                      # 原始 JSON 快照（不入库，本地保留）
├── interim/                  # 中间结果（不入库）
└── processed/                # 全量清洗/标注数据（不入库，本地保留）
```

**入库规则**：`spec/`、`samples/`、`eval/`、`manifests/` 进 Git；`raw/`、`interim/`、`processed/` 不进 Git，避免带入出版商受版权保护的完整摘要或大体积数据。完整数据放本地、网盘或私有存储。

例外：`manifests/import_*.json`、`manifests/load_report_*.md` 是每次导入覆盖的运行产物，不入库（见 `.gitignore`）；验收快照记录在 `docs/09-项目管理/BE2验收记录_v0.1-thin_2026-11-19.md`。

## 2. 当前版本

- 数据契约：`spec/data_contract_v0.1.md`
- 标签体系：`spec/taxonomy_v0.1.md`
- 评测规范：`spec/eval_spec_v0.1.md`
- 薄切片：`v0.1-thin`，100 条成果（6 个主方向 × 15 + 液流/超级电容 × 5）
- 薄切片摘要：`manifests/summary_v0.1-thin.md`（数量、质量、已知限制）
- 需求种子：`samples/demands_seed_v0.1.jsonl`，20 条模拟需求
- 企业画像：`samples/enterprises_seed_v0.1.jsonl`，10 家化名企业
- 评测模板：v0.1-thin 的 `eval/retrieval_queries_v0.1-thin.*`（20 条 query）、`eval/pair_labels_v0.1-thin.*`（50 对 pair）；v0.1 的 `eval/retrieval_queries_v0.1.*`（20 条 query）、`eval/pair_labels_v0.1.*`（50 对 pair）；标注字段为空，待人工标注。
- 全量 `v0.1`：300 条 OpenAlex 成果、100 条模拟需求、25 家化名企业。三个 JSONL 位于 `data/processed/`，通过组内交接包分发。详见 [全量质量报告](manifests/summary_v0.1.md) 和 [数据清单](manifests/dataset_v0.1.json)。

> 说明：`manifests/build_thin_slice_v0.1.json` 中的 `processed_csv` / `sample_csv` / `sample_jsonl` 是构建脚本声明的输出；本次 v0.1 交接包只带 `data/processed/*.jsonl`，当前 JSONL 流程不使用这些 CSV/sample，如需 CSV 可用脚本重跑生成。

## 3. 快速开始

以下命令都在 `Academia-Industry-Match` 仓库根目录运行。只启动前端演示的话，不需要重跑采集或下载全量交接数据。

```bash
# 1) 抓取 OpenAlex 原始快照（默认 relevance + recent 两个视角）
python scripts/data/fetch_openalex.py --run-id thin-20261117 --per-page 100

# 2) 清洗、去重、按子方向分层抽样，生成 100 条薄切片
python scripts/data/build_thin_slice.py --run-id thin-20261117 --version v0.1-thin

# 3) 生成 10 家化名企业 + 20 条模拟需求
python scripts/data/make_seed_data.py

# 4) 生成 20 条检索 query 和 50 个 pair 标注模板
python scripts/data/make_eval_templates.py --version v0.1-thin

# 5) 校验输出
python scripts/data/validate_thin_slice.py --version v0.1-thin
```

环境变量（可选）：

```bash
export OPENALEX_MAILTO="your-team@example.com"
export OPENALEX_API_KEY="..."   # 免费申请：https://openalex.org/settings/api
```

## 4. 数据源政策

| 源 | 用途 | 状态 |
| --- | --- | --- |
| OpenAlex | 论文元数据、摘要、作者/机构、主题、关键词 | 主源 |
| arXiv | 预印本补源/兜底 | 备用 |
| CNIPA 官方批量（ipdps） | 中文专利/法律状态 | 可选，不阻塞 M2 |
| CNKI / 万方 | — | 不抓取（无公开 API，合规风险） |
| Crossref | DOI/期刊/许可补全 | 辅助 |
| Semantic Scholar | 摘要/TLDR 补全 | 可选，需 key |
| 公开榜单/招标/年报 | 需求语料种子 | 人工整理，改写并标记模拟 |

## 5. 版权与公开仓库

- OpenAlex 元数据是 CC0，但摘要版权可能归出版商，**公开仓库不放完整摘要**，`samples/` 里只放截断预览。
- 需求和企业画像都是团队构造的模拟数据，`is_simulated=true`，不对应真实企业。
- 真实企业敏感信息、联系人、未公开需求一律不入库。
- 当前仓库公开可见，完整数据只放本地或私有存储。

## 6. 版本与可复现

每条匹配结果都绑定 `dataset_version + taxonomy_version + embedding_model_version`。原始快照保持只读；清洗和标注结果可从 `raw/` 加脚本重跑得到。每次运行都会在 `manifests/` 生成清单（数量、来源、hash、错误）。

### 私有交接数据与需求核验

需求核验针对 S-02 v0.1 交接的 100 条需求和 25 家模拟企业。详细结论见[需求核验报告](manifests/demands_review_v0.1.md)，可公开的统计证据见[检查清单](manifests/demands_review_checks_v0.1.json)。这两份文件都在仓库内，不依赖原提交者的课程文件夹。

全量交接包不在 Git 里，需要复核时找数据负责人拿对应版本，解压到任意目录即可。解压根目录保持如下结构：

```text
<private-data-root>/
└── data/
    └── processed/
        ├── demands_v0.1.jsonl
        └── enterprises_v0.1.jsonl
```

在仓库根目录执行下面这条只读检查命令，把占位路径换成自己的解压目录：

```bash
python scripts/data/review_demands.py --data-root "/path/to/private-handoff" --output data/manifests/demands_review_checks_v0.1.json
```

脚本只读输入、不改原始记录，也不会自动写回报告里的建议补丁。它会重算基础字段、模拟标记、来源归类、内容哈希、精确重复和文本相似候选；业务合理性与公开来源正文仍需人工核对。手头没有私有交接包时，直接看报告和清单文件即可，不要把仓库里 20 条需求样例当成 100 条全量数据。

如果要重建前端样例，另需 `data/processed/achievements_clean_v0.1.jsonl`，操作见[前端 README](../frontend/README.md)。所有脚本都通过参数传路径，不要求交接包和仓库放在同级目录。

## 7. 相关文档

- [数据口径更正记录](../docs/03-项目计划/数据口径更正记录_v0.1.md)：BGE-M3 维度、数据源与模拟数据口径
- [项目文档索引](../docs/README.md)：项目文档总索引
