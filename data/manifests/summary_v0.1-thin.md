# 薄切片 v0.1-thin 摘要

- 生成日期：2026-11-17/18
- 数据源：OpenAlex
- run_id：`thin-20261117`
- 数据版本：`v0.1-thin`
- 标签版本：`v0.1`
- 全量文件：`data/processed/achievements_clean_v0.1-thin.jsonl`（本地，不入 git；随交接包 v3 分发，v2 及更早版本作废）
- 可入库样例：`data/samples/achievements_sample_v0.1-thin.jsonl`（20 条，摘要正文截断至 600 字符，末尾加省略号，总长 ≤601）

> 注：`data/manifests/fetch_openalex_thin-20261117.json` 是最近一次重跑的清单。重跑会跳过已有 raw 文件，因此其中的 `total_returned` 只反映当次新抓请求；完整抓取统计以 `build_thin_slice_v0.1-thin.json` 和本摘要为准。

## 1. 数量与分布

| 项 | 数值 |
| --- | ---: |
| 原始快照文件 | 42 个 JSON |
| 原始响应记录 | 3,736 |
| 规范化后 | 3,646 |
| 规范化丢弃 | 90 |
| 去重后 | 3,149 |
| 去重删除 | 497 |
| 领域过滤剔除 | 218 |
| 入选成果 | 100 |
| 模拟需求 | 20 |
| 化名企业 | 10 |
| 检索 query | 20 |
| pair 标注 | 50（40 同领域 + 10 跨领域） |

| 子方向 | 入选 |
| --- | ---: |
| 正极材料 | 15 |
| 负极材料 | 15 |
| 电解质 | 15 |
| 隔膜 | 15 |
| 电芯与系统 | 15 |
| 回收与梯次利用 | 15 |
| 液流电池（辅） | 5 |
| 超级电容（辅） | 5 |

## 2. 质量指标

| 指标 | 结果 |
| --- | --- |
| 语言 | 100 条英文；中文画像待 LLM 生成 |
| 年份 | 2020: 5；2021: 10；2022: 14；2023: 17；2024: 21；2025: 16；2026: 17 |
| 摘要长度 | 208—3,639 字符，平均 1,392.7 |
| 缺失 DOI | 1 条 |
| `license_missing` | 33 条 |
| `no_institutions` | 1 条 |
| `language_metadata_corrected` | 1 条（OpenAlex 把英文记录标成 zh，已纠正为 en） |
| 主题字段非空 | 100 条 |
| 候选集 | 每条 query 20 条成果 |
| pair 多样性 | 50 对覆盖 45 个不同成果 |

## 3. 已知限制

1. **成果语料为英文**：OpenAlex 的中文论文覆盖不足；中文展示依赖后续 `capability_profile_zh`（机器生成，需标记）。
2. **材料体系覆盖不均衡**：正极已覆盖高镍、LFP、钠电、钴酸锂/钴-free；负极以硬碳为主，硅基 3 条、石墨/硅-石墨若干。全量 300—400 条时需增加子主题配额与专项查询。
3. **q20（消费电子高电压钴酸锂）候选较弱**：薄切片中只有 1 条 LFP/LCO 对比论文较接近；全量数据后重新标注。
4. **尚未做 LLM 抽取/向量化/入库**：本版本只到“清洗 + 抽样 + 评测模板”；标签、TRL、画像、embedding、pgvector 是下一步。
5. **摘要版权**：公开仓库只放截断样例；完整摘要留在 `data/processed/`，不提交公开仓库。

## 4. 复现命令

```bash
python scripts/data/fetch_openalex.py --run-id thin-20261117 --per-page 100
python scripts/data/build_thin_slice.py --run-id thin-20261117 --version v0.1-thin
python scripts/data/make_seed_data.py
python scripts/data/make_eval_templates.py --version v0.1-thin
python scripts/data/validate_thin_slice.py --version v0.1-thin
```

## 5. 下一步

1. `extract_labels.py`：Qwen 抽取 `tech_field`/应用场景/TRL/性能指标，带证据和 confidence；先跑 30 条校准。
2. `embed.py`：BGE-M3 1024（或 Qwen 1024）向量化 `capability_profile`/`need_profile`，缓存 `text_hash`。
3. `load_db.py`：PostgreSQL 16 + pgvector 0.8.x 幂等导入。
4. `evaluate.py`：本冲刺先做 B0—B2 三组基线（BM25 / 纯向量 / 标签+向量），B3（三层精排）待匹配引擎就绪后补；输出 Recall@10、Precision@5、nDCG@10。
5. 全量扩展到 300—400 条成果 + 100 条需求 + 25 家企业画像；补齐钴酸锂、硅基、石墨等子主题配额。
