# 检索与匹配评测规范 v0.1

> 项目：技术转化智能匹配与产学研对接系统（课题 7，G04）
> 版本：v0.1
> 日期：2026-11-17
> 负责人：陈镇灏（AI）、黄欣悦（DE）
> 关联：`data_contract_v0.1.md`、`taxonomy_v0.1.md`

## 0. 目的

在数据全量入库前，先建立一套**可复核、可复现**的评测集，用来回答三个问题：

1. 向量召回是否能找到技术上相关的成果？
2. 标签硬过滤 + 向量召回 + LLM 精排是否比单路基线更好？
3. 推荐理由/风险是否与实际匹配依据一致？

评测集不是“最后补的材料”，而是数据构建的一部分，必须在 D2/D3 阶段就开始标注。

## 1. 评测对象

| 评测 | 输入 | 输出 | 用途 |
| --- | --- | --- | --- |
| 检索评测 | 20 条 query + 候选成果 | 相关成果排序 | 评估向量召回/混合召回 |
| 配对评测 | 50 个（成果,需求）对 | 0/1/2 relevance | 评估 LLM 精排与理由 |
| 标签评测 | 30 条人工标注成果 | 逐字段准确率 | 评估 LLM 抽取 |
| TRL 评测 | 20 条边界样本 | TRL 偏差/一致性 | 评估 TRL 初评 |

## 2. 检索 query 集

### 2.1 组成

共 20 条：

- **中文业务 query（10 条）**：模拟企业技术负责人的表述，带指标/场景/约束。
- **英文学术 query（8 条）**：模拟科研人员/技术转移人员的检索语言。
- **跨语言/困难 query（2 条）**：中文 query 找英文成果，或跨两个子方向。

按 `query_language` 统计为 zh 11 / en 9，因为 2 条跨语言 query 分别使用中文和英文；按 `query_type` 统计为 10 / 8 / 2。

覆盖 8 个 `tech_field`：正极、负极、电解质、隔膜、电芯/系统、回收、液流、超级电容。至少 2 条跨领域 query，用于检验硬过滤与 hard negative。

### 2.2 构造原则

1. **不要照抄成果标题/摘要**；用需求方语言改写，避免“关键词泄漏”。
2. **带约束**：至少一半 query 包含性能指标、TRL、应用场景或合作模式。
3. **有硬负样本**：候选集里放同领域但场景/TRL 不匹配的成果，以及跨领域但字面相似的成果。
4. **中英文都要有**：检验 BGE-M3 的跨语言能力。
5. **query 不引用作者/机构**：匹配应基于技术本身，符合匿名设计。

### 2.3 候选集

每条 query 的候选集：

- 目标 `tech_field` 的全部薄切片成果（约 15 条）；
- 加 5 条跨领域/相邻领域成果作为 hard negative；
- 候选集上限 20 条，按 `achievement_id` 去重。

标注人**只看候选集**，不看成败集的全部 100 条；这样可以控制标注成本，也保证不同 query 的 Recall 可比。

### 2.4 标注

- `relevance_grade`：2 = 强相关，1 = 部分相关，0 = 不相关。
- 每条 query 至少标 5 条相关（2 或 1）；如果确实不足 5 条，记录原因。
- 标注时只看技术内容，不看作者、机构、期刊、引用数；避免名气偏差。
- 20% 的 query 由第二人复核；分歧记录到 `adjudication`。

## 3. 配对评测集

### 3.1 组成

共 50 对：

- **40 对同领域**：20 条需求 × 每个需求 2 条同 `tech_field` 成果；
- **10 对跨领域 hard negative**：从前 10 条需求各取 1 条不同 `tech_field` 成果。

后续可扩展到 100 对，加入：
- 同领域不同应用场景（`same_field_diff_scenario`）
- 同领域 TRL 差距大（`same_field_trl_gap`）
- 字面相似但技术不同（`lexical_trap`，如 solid electrolyte vs solid oxide fuel cell）

### 3.2 相关性量表

| 分数 | 含义 | 判定参考 |
| ---: | --- | --- |
| 2 | 强相关 | 技术领域一致；应用场景一致或兼容；TRL 差距 ≤2；合作模式可兼容；关键指标不冲突 |
| 1 | 部分相关 | 技术领域一致，但场景/TRL/合作模式有一项明显不匹配；或技术领域相邻但可迁移 |
| 0 | 不相关 | 技术领域不同且不可迁移；或关键约束冲突（如需求要求中试，成果仅 TRL 2） |

**注意**：分数是“技术适配度”，不是“成交概率”；不要把“机构名气”“论文引用高”当作加分项。

### 3.3 标注流程

1. AI 生成候选对（同领域 + 跨领域），写入 `data/eval/pair_labels_v0.1-thin.csv`。
2. DE + AI 各自独立标 50 对；至少 20% 双标。
3. 计算 Cohen's kappa（加权）；目标 ≥0.6。
4. 裁决会：对 0/1/2 边界、跨领域对、TRL 差距大的对逐条讨论；记录理由。
5. 冻结 `pair_labels_v0.1-thin`，作为 LLM 精排的基线。

## 4. 指标

### 4.1 检索

| 指标 | 定义 | 目标 |
| --- | --- | ---: |
| Recall@10 | Top-10 中相关成果数 / 全部相关成果数 | ≥0.70 |
| Precision@5 | Top-5 中相关成果数 / 5 | ≥0.70 |
| MRR | 第一个相关结果的倒数排名均值 | 报告 |
| nDCG@10 | 按 0/1/2 分级折损累计增益 | ≥0.70（建议） |

### 4.2 配对/精排

| 指标 | 定义 | 目标 |
| --- | --- | --- |
| nDCG@10 | 按人工 0/1/2 评分 | ≥0.70 |
| Spearman ρ | LLM 分数与人工分数的秩相关 | ≥0.60 |
| Top-1 准确率 | 每需求最高分对是否为人工 2 分 | 报告 |
| 理由一致率 | 理由中的依据能在双方文本中找到 | ≥90% |
| 风险一致性 | 四维风险与人工判断方向一致 | ≥80% |

### 4.3 标签/TRL

| 指标 | 目标 |
| --- | ---: |
| `tech_field` 准确率 | ≥90% |
| `application_scenario` 准确率 | ≥85% |
| `cooperation_mode` 准确率（需求侧） | ≥90% |
| TRL 平均绝对误差 | ≤1 级 |
| TRL 相邻一致率（±1 级） | ≥80% |

### 4.4 调用开销/时延

- 每次匹配的 LLM token 数、费用、时延；
- 100 对精排的总调用开销；
- 向量化 100/300—400 条的耗时；
- 失败/重试率。

## 5. 基线对比

至少跑四组，形成消融：

| 基线 | 说明 | 本冲刺 |
| --- | --- | --- |
| B0：BM25/关键词 | 只用文本关键词，不用向量 | 做 |
| B1：纯向量 | 只用 embedding 相似度 | 做 |
| B2：标签硬过滤 + 向量 | 当前 Layer 1 + Layer 2；任一 `tech_field` 命中即可 | 做 |
| B2-primary：主标签消融 | 仅用 primary `tech_field` 过滤，用于诊断 | 做 |
| B3：标签 + 向量 + LLM 精排 | 完整三层 | 待匹配引擎就绪后补 |

数据侧第一次冲刺先交付 B0—B2；B2-primary 作为消融，不计入主结论；B3 依赖匹配引擎/LLM 精排，不在本次范围。报告每组 Recall@10、Precision@5、nDCG@10、调用开销、时延。答辩时用 B0→B3 的增量证明三层架构的价值。

## 6. 文件与字段

### 6.1 `data/eval/retrieval_queries_v0.1-thin.csv`

| 列 | 说明 |
| --- | --- |
| `query_id` | `q01`—`q20` |
| `query_text` | 查询文本 |
| `query_language` | `zh`/`en`/`mixed` |
| `query_type` | `zh_business`/`en_academic`/`cross_lingual`/`hard_negative` |
| `target_tech_field` | 目标枚举 code，多个用 `;` |
| `candidate_achievement_ids` | 候选成果 ID，`;` 分隔 |
| `relevant_achievement_ids` | 人工填写，`;` 分隔 |
| `relevance_grades` | 人工填写，`id:2;id:1` |
| `annotator` | 标注人 |
| `notes` | 备注 |

### 6.2 `data/eval/pair_labels_v0.1-thin.csv`

| 列 | 说明 |
| --- | --- |
| `pair_id` | `pair_001`—`pair_050` |
| `demand_id` | 需求 ID |
| `demand_title` | 需求标题（便于阅读） |
| `achievement_id` | 成果 ID |
| `achievement_title` | 成果标题（便于阅读） |
| `pair_source` | `same_field`/`cross_field` |
| `hard_negative_type` | `cross_field`/`same_field_diff_scenario`/`same_field_trl_gap`/`lexical_trap`/`none` |
| `relevance_grade` | 人工填 0/1/2 |
| `rationale` | 人工填理由 |
| `annotator` | 标注人 |
| `adjudication` | 分歧裁决 |

### 6.3 评测报告

输出到 `data/manifests/eval_report_v0.1.md`，包含：

- 数据版本、评测集版本、模型版本；
- 每条 query 的 Top-10 和人工相关标注（机器可读明细另存 `baseline_<version>_top10.csv`）；
- 基线指标表（B0—B3；本冲刺先交 B0—B2 和 B2-primary 消融，B3 后续补）；
- 错误分析：假阳性/假阴性各 5 例；
- 结论与下一步。
- 复现时必须固定 query 向量缓存（`data/interim/eval_query_vectors_<version>.jsonl`）并记录其 SHA-256；不得静默重生成后覆盖旧报告。

## 7. 验收与冻结

当前 `retrieval_queries_v0.1-thin.*` 和 `pair_labels_v0.1-thin.*` 的标注字段为空，是待标注模板。完成首轮标注后按以下条件冻结：

1. 20 条 query + 50 对 pair 全部完成首轮标注；
2. 20% 双标，kappa ≥0.6；
3. 冻结 `eval_v0.1`，写入 `dataset_manifest`；
4. 后续每次改标签体系、Embedding 模型、文本表示，必须重跑评测并保留旧报告；
5. 评测集不参与训练/调参；只用于评估（避免过拟合）。

## 8. 版本记录

| 版本 | 日期 | 变更 | 负责人 |
| --- | --- | --- | --- |
| v0.1 | 2026-11-17 | 初版：20 query + 50 pair；0/1/2 量表；四组基线 | 陈镇灏、黄欣悦 |
