# 数据契约 v0.1

> 项目：技术转化智能匹配与产学研对接系统（课题 7，G04）
> 版本：v0.1
> 日期：2026-11-17
> 状态：评审通过后冻结，作为 D1/D2/D7 的共同基线
> 负责人：黄欣悦（DE）、陈镇灏（AI）、张小桐（BE2）
> 批准：贾越（PM）
> 关联文档：`taxonomy_v0.1.md`、`eval_spec_v0.1.md`、`data/README.md`

## 0. 结论先行

1. **数据源以 OpenAlex 为主**：论文元数据、摘要、作者/机构、主题、关键词；arXiv 只做补源；CNKI/万方不抓取；CNIPA 专利作为可选项，不进入 M2 关键路径。
2. **成果语料以英文为主**：OpenAlex 的中文论文覆盖不足，因此中文展示通过 LLM 生成的 `capability_profile_zh` 解决，原始摘要保留可追溯，机器生成文本必须标记。
3. **需求侧以模拟数据为主**：20—30 条来自公开榜单/招标/年报的改写，70—80 条团队构造；全部 `is_simulated=true`，企业使用化名。
4. **先冻结字段、枚举与版本规则**，再抓取；任何新增字段或枚举变更走变更控制。
5. **BGE-M3 dense 向量为 1024 维**，计划书中的“768 维”是笔误；Embedding 维度不得写死在表结构之外，必须记录在 `embedding` 记录中。

## 1. 目的与适用范围

本契约定义从数据采集到匹配评测之间所有数据对象的字段、类型、必填性、来源、枚举、版本、质量规则和验收口径。适用于：

- 数据采集脚本（`scripts/data/fetch_*.py`）
- 清洗/构建脚本（`scripts/data/build_*.py`）
- LLM 抽取脚本（`scripts/data/extract_*.py`）
- 向量化脚本（`scripts/data/embed.py`）
- 数据库迁移与导入（`migrations/`、`scripts/data/load_db.py`）
- 匹配引擎与前端展示的字段口径

本契约不替代数据库 DDL；DDL 由 BE2 依据本契约编写，任何冲突以本契约为准并回写迁移说明。

## 2. 数据源政策

| 源 | 提供内容 | 访问方式 | 许可/限制 | 本项目用法 |
| --- | --- | --- | --- | --- |
| OpenAlex | 论文元数据、摘要（部分）、作者/机构、主题、关键词、引用、OA 状态 | REST API；免费 key $1/天，无 key 共享 $0.10/天 | 元数据 CC0；摘要版权可能属于出版商 | **主源**：成果 400 条 |
| arXiv | 预印本元数据、完整摘要、作者、许可 | Atom API；请求间隔 ≥3 秒 | 按单篇许可；预印本未经同行评审 | **补源/兜底**：低覆盖子方向 |
| CNIPA 官方批量 | 中文专利著录项、摘要、法律状态 | `ipdps.cnipa.gov.cn` 实名注册 + FTP；PSS 批量每次约 40 条 | 官方数据开放目录/使用条款 | **可选**：50—100 条专利，2 天时间盒 |
| CNKI / 万方 | 中文论文 | 无公开 API，订阅/反爬 | 抓取存在合规风险 | **不抓取** |
| Crossref | DOI、期刊、许可 | REST API | 元数据开放 | 只做 DOI/期刊补全 |
| Semantic Scholar | 摘要、TLDR、引用 | REST API；无 key 易 429 | 按 API 条款 | 可选补摘要，需 key |
| 公开榜单/招标/年报 | 企业技术需求语料 | 人工检索、阅读、改写 | 只使用公开信息，不大段复制 | **需求种子**：20—30 条改写 |

**采集红线**：不抓取需要登录/付费/验证码的页面；不绕过反爬；不采集个人联系方式；不把真实企业未公开需求写入数据库；不将原始摘要全文提交到公开仓库。

## 3. 实体与关系

```text
raw_source_record 1 ── * achievement
achievement 1 ── * achievement_text
achievement 1 ── * achievement_tag
achievement 1 ── 1 achievement_extraction
achievement 1 ── * embedding
enterprise 1 ── * demand
demand 1 ── * demand_tag
demand 1 ── * embedding
achievement * ── * demand  (match_score)
match_score 1 ── * match_evidence
eval_query 1 ── * eval_label
pipeline_run 1 ── * dataset_manifest
```

核心原则：**raw 不可变；curated 可审核；derived 可重建**。每个派生字段都能追溯到原始记录、模型、Prompt 和证据片段。

## 4. 字段定义

### 4.1 `raw_source_record`（原始快照）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `raw_id` | string | 是 | `sha256(source + source_id + retrieved_at)` |
| `source` | enum(`openalex`/`arxiv`/`cnipa`) | 是 | 数据源 |
| `source_id` | string | 是 | 源内 ID（OpenAlex 为 `W...`） |
| `query_tag` | string | 是 | 采集子方向（`cathode` 等） |
| `lens` | enum(`relevance`/`recent`/`cited`) | 否 | 采集视角 |
| `source_url` | string | 是 | 可访问的源 URL |
| `retrieved_at` | datetime(UTC) | 是 | 取得时间 |
| `http_status` | int | 是 | HTTP 状态码 |
| `payload` | json | 是 | 原始响应/记录 |
| `payload_hash` | string | 是 | sha256 |
| `license` | string | 否 | 源声明的许可 |
| `dataset_version` | string | 是 | 如 `v0.1-thin` |
| `raw_path` | string | 是 | 本地快照路径（相对项目根） |

### 4.2 `achievement`（成果主表）

| 字段 | 类型 | 必填 | 来源/说明 |
| --- | --- | --- | --- |
| `achievement_id` | string | 是 | `ach_{source}_{source_id}` |
| `source` | enum | 是 | `openalex`/`arxiv`/`cnipa` |
| `source_id` | string | 是 | 源内 ID |
| `doi` | string | 否 | 归一化小写，不带 `https://doi.org/` |
| `patent_no` | string | 否 | 专利号；论文为空 |
| `title_original` | text | 是 | 原始标题 |
| `abstract_original` | text | 是 | 原始摘要；缺失时不得编造，标记 `abstract_missing` |
| `language` | enum(`en`/`zh`/`mixed`/`unknown`) | 是 | 源语言 |
| `publication_year` | int | 是 | 2000—2026；目标 2020—2026 |
| `publication_date` | date | 否 | ISO 8601 |
| `type` | enum(`article`/`review`/`preprint`/`patent`/`other`) | 是 | 成果类型 |
| `venue` | string | 否 | 期刊/会议/专利局 |
| `authors` | json array | 否 | 作者姓名列表 |
| `institutions` | json array | 否 | 机构列表 |
| `countries` | json array | 否 | 国家代码列表 |
| `keywords` | json array | 否 | 源关键词 |
| `topics` | json array | 否 | 源主题（OpenAlex topics） |
| `cited_by_count` | int | 否 | 引用数；未知为 null |
| `source_url` | string | 是 | 原文/落地页 |
| `license` | string | 否 | 许可；未知为 null |
| `oa_status` | string | 否 | OpenAlex OA 状态 |
| `retrieved_at` | datetime(UTC) | 是 | 取得时间 |
| `content_hash` | string | 是 | 归一化标题+摘要+DOI+source_id 的 sha256 |
| `clean_status` | enum(`raw`/`cleaned`/`labeled`/`embedded`/`published`) | 是 | 流水线状态 |
| `review_status` | enum(`pending`/`approved`/`rejected`/`needs_review`) | 是 | 人工审核状态 |
| `quality_flags` | json array | 是 | 见 6.1 |
| `is_simulated` | bool | 是 | 成果默认 `false` |
| `dataset_version` | string | 是 | 如 `v0.1-thin` |
| `created_at` | datetime | 是 | |
| `updated_at` | datetime | 是 | |

### 4.3 `achievement_text`（派生文本）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text_id` | string | 是 | `txt_{achievement_id}_{text_type}_{lang}` |
| `achievement_id` | string | 是 | FK |
| `text_type` | enum(`title_zh`/`abstract_zh`/`capability_profile_zh`/`capability_profile_en`) | 是 | 文本类型 |
| `language` | enum(`zh`/`en`) | 是 | 文本语言 |
| `text` | text | 是 | 文本内容 |
| `method` | enum(`original`/`machine`/`human`/`llm`) | 是 | 生成方式；机器生成必须标记 |
| `model` | string | 否 | 如 `qwen3.8-flash` |
| `prompt_version` | string | 否 | Prompt 版本 |
| `text_hash` | string | 是 | 归一化文本 sha256；用于 embedding 缓存 |
| `created_at` | datetime | 是 | |

**规则**：`capability_profile_zh` 不是逐字翻译，而是面向产业语言的技术能力摘要（150—250 字）；必须保留 `abstract_original` 用于证据。演示/答辩时明确说明“机器生成画像，原文为准”。

### 4.4 `achievement_tag`（成果标签）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `tag_id` | string | 是 | |
| `achievement_id` | string | 是 | FK |
| `dimension` | enum(`tech_field`/`application_scenario`/`cooperation_mode`) | 是 | 维度 |
| `code` | string | 是 | 枚举 code，见 `taxonomy_v0.1.md` |
| `is_primary` | bool | 是 | `tech_field` 必须且只能有一个 primary |
| `confidence` | float(0—1) | 是 | 模型置信度 |
| `evidence` | text | 否 | 原文摘录；无证据时 confidence ≤0.4 |
| `method` | enum(`llm`/`rule`/`human`) | 是 | 生成方式 |
| `model` | string | 否 | 抽取模型 |
| `prompt_version` | string | 否 | Prompt 版本 |
| `review_status` | enum(`pending`/`approved`/`rejected`) | 是 | |
| `created_at` | datetime | 是 | |

### 4.5 `achievement_extraction`（抽取结果）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `extraction_id` | string | 是 | |
| `achievement_id` | string | 是 | FK |
| `material_system` | string | 否 | 如“硫化物固态电解质” |
| `key_metrics` | json array | 否 | `[{name,value,unit,evidence}]` |
| `process` | json array | 否 | 工艺/制备路线关键词 |
| `trl` | int(1—9) | 否 | 技术成熟度；无证据为 null |
| `trl_confidence` | float(0—1) | 否 | |
| `trl_evidence` | text | 否 | 原文依据 |
| `ip_status` | enum(`granted`/`pending`/`published`/`unknown`) | 是 | 论文默认 `unknown`；专利按法律状态 |
| `extraction_run_id` | string | 是 | 关联 `pipeline_run` |
| `model` | string | 是 | |
| `prompt_version` | string | 是 | |
| `raw_output` | json | 否 | 模型原始输出，便于复核 |
| `review_status` | enum(`pending`/`approved`/`rejected`) | 是 | |
| `created_at` | datetime | 是 | |

### 4.6 `embedding`（向量）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `embedding_id` | string | 是 | |
| `object_type` | enum(`achievement`/`demand`/`eval_query`) | 是 | |
| `object_id` | string | 是 | |
| `text_type` | enum(`title`/`abstract`/`capability_profile`/`need_profile`) | 是 | 向量化文本类型 |
| `model` | string | 是 | `BAAI/bge-m3` 或 `qwen3.7-text-embedding-flash` |
| `dim` | int | 是 | **1024** |
| `text_hash` | string | 是 | 与文本表一致 |
| `vector` | vector(1024) | 是 | pgvector；JSONL 中为 float 数组 |
| `dataset_version` | string | 是 | |
| `created_at` | datetime | 是 | |

唯一约束：`(object_type, object_id, text_type, model, text_hash)`。更换模型或文本必须重算，不得混维。

### 4.7 `enterprise`（企业画像）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `enterprise_id` | string | 是 | |
| `display_name` | string | 是 | 化名，如“某长三角动力电池企业” |
| `legal_name` | string | 否 | 真实企业名仅内部留存，不对外展示 |
| `industry` | enum(`battery_manufacturing`/`material_manufacturing`/`ev_oem`/`ess_integrator`/`recycling`/`other`) | 是 | |
| `size` | enum(`large`/`medium`/`small`) | 是 | |
| `region` | enum(`yangtze_delta`/`pearl_river_delta`/`beijing_tianjin_hebei`/`chengdu_chongqing`/`other`/`any`) | 是 | |
| `main_business` | text | 是 | 主营业务 |
| `tech_base` | text | 否 | 现有技术基础 |
| `resources` | text | 否 | 可投入资金/场地/人员 |
| `prior_collaboration` | text | 否 | 既往产学研经历 |
| `is_simulated` | bool | 是 | 模拟企业为 `true` |
| `source_note` | text | 是 | 来源说明；模拟数据必须说明“团队构造，不对应真实企业” |
| `created_at` | datetime | 是 | |

### 4.8 `demand`（企业需求）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `demand_id` | string | 是 | |
| `enterprise_id` | string | 是 | FK |
| `title` | string | 是 | 需求标题 |
| `pain_point` | text | 是 | 技术痛点 |
| `expected_solution` | text | 是 | 期望方案 |
| `technical_metrics` | json array | 是 | `[{name,value,unit}]` |
| `budget_range` | string | 否 | 如“500—1000 万元” |
| `timeline` | string | 否 | 如“18 个月” |
| `cooperation_modes` | json array | 是 | 枚举 code |
| `required_trl` | int(1—9) | 是 | 企业可接受的最低 TRL |
| `tech_fields` | json array | 是 | 枚举 code |
| `application_scenarios` | json array | 是 | 枚举 code |
| `ip_requirement` | text | 否 | IP 要求 |
| `region` | enum | 是 | 意向地区 |
| `status` | enum(`draft`/`active`/`expired`/`closed`) | 是 | |
| `valid_until` | date | 是 | 有效期 |
| `is_simulated` | bool | 是 | 模拟需求必须为 `true` |
| `source_note` | text | 是 | 公开种子 URL 或模拟说明 |
| `source_urls` | json array | 否 | 公开种子来源 |
| `content_hash` | string | 是 | |
| `dataset_version` | string | 是 | |
| `created_at` | datetime | 是 | |
| `updated_at` | datetime | 是 | |

### 4.9 `demand_tag`（需求标签）

字段与 `achievement_tag` 相同，外键改为 `demand_id`。需求侧 `tech_field` 至少 1 个、最多 2 个；`cooperation_mode` 1—3 个；均允许 `unknown` 兜底。

### 4.10 `match_score`（匹配结果）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `match_id` | string | 是 | |
| `achievement_id` | string | 是 | |
| `demand_id` | string | 是 | |
| `total_score` | float(0—100) | 是 | 适配度，不是成交概率 |
| `tag_score` | float(0—100) | 是 | 标签重叠/硬约束 |
| `semantic_score` | float(0—100) | 是 | 向量相似度归一化 |
| `llm_score` | float(0—100) | 否 | LLM 精排分 |
| `reason` | text | 是 | 推荐理由 |
| `risk` | json | 是 | 四维风险：技术/市场/IP/合作 |
| `evidence` | json | 是 | 引用片段与字段 |
| `model` | string | 是 | 精排模型 |
| `prompt_version` | string | 是 | |
| `dataset_version` | string | 是 | |
| `taxonomy_version` | string | 是 | |
| `embedding_model_version` | string | 是 | |
| `is_stale` | bool | 是 | 数据/模型变更后标记失效 |
| `created_at` | datetime | 是 | |

### 4.11 评测对象

**`eval_query`**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query_id` | string | 是 | 如 `q01` |
| `query_text` | text | 是 | 中文业务/英文/跨语言 |
| `query_language` | enum(`zh`/`en`/`mixed`) | 是 | |
| `query_type` | enum(`zh_business`/`en_academic`/`cross_lingual`/`hard_negative`) | 是 | |
| `target_tech_fields` | json array | 是 | 目标枚举 code |
| `candidate_achievement_ids` | json array | 是 | 候选集，标注时只看这些 |
| `relevant_achievement_ids` | json array | 否 | 人工标注 |
| `relevance_grades` | json object | 否 | `{achievement_id: 0/1/2}` |
| `annotator` | string | 否 | |
| `notes` | text | 否 | |
| `dataset_version` | string | 是 | |

**`eval_label`（pair 标注）**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `pair_id` | string | 是 | |
| `achievement_id` | string | 是 | |
| `demand_id` | string | 是 | |
| `relevance_grade` | int(0/1/2) | 否 | 人工标注 |
| `rationale` | text | 否 | 判定理由 |
| `hard_negative_type` | enum(`cross_field`/`same_field_diff_scenario`/`same_field_trl_gap`/`lexical_trap`/`none`) | 否 | 负样本类型 |
| `annotator` | string | 否 | |
| `adjudication` | text | 否 | 分歧裁决 |
| `dataset_version` | string | 是 | |

### 4.12 `pipeline_run` / `dataset_manifest`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `run_id` | string | 是 | 如 `thin-20261117` |
| `stage` | enum(`fetch`/`clean`/`extract`/`embed`/`load`/`match`/`eval`) | 是 | |
| `started_at`/`finished_at` | datetime | 是 | |
| `status` | enum(`running`/`success`/`partial`/`failed`) | 是 | |
| `input_count`/`output_count` | int | 是 | |
| `config` | json | 是 | 查询、模型、参数 |
| `git_commit` | string | 否 | |
| `dataset_version` | string | 是 | |
| `log_path` | string | 否 | |

`dataset_manifest` 记录版本、来源 run、数量、hash、taxonomy_version、embedding_model、备注。

## 5. 枚举

所有枚举以 `taxonomy_v0.1.md` 为准。禁止在代码中硬编码中文标签作为主键；数据库存 code，展示层做 label 映射。

核心枚举：

- `tech_field`：`cathode_material`、`anode_material`、`electrolyte`、`separator`、`cell_system`、`recycling`、`flow_battery`、`supercapacitor`
- `application_scenario`：`ev_power`、`grid_storage`、`cni_storage`、`residential_storage`、`consumer_electronics`、`e_tool_two_wheeler`、`special`、`recycling_industry`
- `cooperation_mode`：`transfer`、`license`、`joint_rd`、`joint_lab`、`tech_service`
- `ip_status`：`granted`、`pending`、`published`、`unknown`
- `language`：`en`、`zh`、`mixed`、`unknown`
- `type`：`article`、`review`、`preprint`、`patent`、`other`

## 6. 质量规则

### 6.1 `quality_flags` 允许值

`abstract_reconstructed`、`abstract_missing`、`abstract_short`、`license_missing`、`no_institutions`、`no_keywords`、`language_unknown`、`language_metadata_corrected`、`possible_duplicate`、`out_of_domain`、`title_suspect`、`needs_human_review`、`translated_machine`、`profile_machine`。

### 6.2 采集与清洗

| 规则 | 要求 |
| --- | --- |
| 身份唯一 | `source + source_id` 唯一；DOI 归一化后唯一 |
| 必填完整 | `title_original`、`abstract_original`、`language`、`publication_year`、`source_url`、`retrieved_at`、`content_hash` 100% 非空 |
| 摘要长度 | 100—8000 字符；<100 标记 `abstract_short` 并进入人工复核 |
| 年份 | 2000—2026；目标 2020—2026 |
| 语言 | `en`/`zh`/`mixed`/`unknown`；未知不得强行标 `en` |
| 去重 | DOI/源 ID 精确去重 + 归一化标题 + 摘要 SimHash；重复率 <2% |
| 领域相关 | 必须命中至少一个“上下文词”（battery/lithium/cell 等）和一个“主题词”（cathode/anode/electrolyte 等） |
| 标题排除 | `correction`、`erratum`、`retraction`、`editorial`、`comment on`、`reply to`、`retracted` 等不进入成果集 |
| 来源追溯 | 每条有 `source_url`、`retrieved_at`、`license`（未知为 null）、`raw_path` |

### 6.3 标签与抽取

| 规则 | 要求 |
| --- | --- |
| 标签枚举 | 只能输出 taxonomy 中的 code；非法 code 直接拒绝 |
| 标签覆盖 | ≥95% 成果至少 1 个 `tech_field` |
| 主标签 | 每个成果恰好 1 个 `is_primary=true` 的 `tech_field` |
| 证据 | 每个标签有 `evidence`；无证据时 `confidence ≤0.4` 且 `review_status=needs_review` |
| TRL | 1—9 整数；必须给 `trl_evidence` 或人工确认；论文不得无依据标 7—9 |
| 合作模式 | 成果侧只作为“潜在模式”推断，`confidence ≤0.5`，不用于硬过滤；需求侧按企业填报 |
| 未知处理 | 不确定写 `unknown`，禁止编造 IP 状态、合作模式、性能指标 |
| 人工抽检 | 10% 样本、≥30 条，逐字段比对；标签准确率 ≥90% |

### 6.4 向量与匹配

| 规则 | 要求 |
| --- | --- |
| 维度 | 同一模型 1024 维；不得混用 768/1024 |
| 覆盖率 | 成果/需求向量覆盖率 100% |
| 文本来源 | 向量化 `capability_profile`/`need_profile`，原始摘要只做证据 |
| 文本 hash | 每条向量绑定 `text_hash`；文本变化必须重算 |
| 版本 | 匹配结果绑定 `dataset_version + taxonomy_version + embedding_model_version` |
| 失效 | 任一版本变化，旧匹配 `is_stale=true`，重算后再展示 |

## 7. 验收标准

### 7.1 薄切片 v0.1-thin（本周）

| 指标 | 目标 |
| --- | ---: |
| 成果数量 | 100 条（6 主方向 × 15 + 液流/超级电容 × 5） |
| 需求数量 | 20 条（模拟种子） |
| 企业画像 | 10 家（化名） |
| 检索 query | 20 条 |
| pair 标注模板 | 50 对 |
| 来源可追溯 | 100% |
| 必填字段完整率 | ≥98%（薄切片） |
| 重复率 | <2% |
| 标签覆盖 | ≥95%（若已跑抽取） |
| 向量覆盖 | 100%（若已跑 embedding） |

### 7.2 全量 v0.1（M2/M3）

| 指标 | 目标 |
| --- | ---: |
| 成果数量 | 400 条（300—500 可接受） |
| 需求数量 | 100 条 |
| 企业画像 | 25 家 |
| 检索 query | 20—30 条 |
| pair 标注 | 50—100 对 |
| 来源可追溯 | 100% |
| 必填字段完整率 | ≥95% |
| 重复率 | <2% |
| 标签覆盖率 | ≥95% |
| 标签抽检准确率 | ≥90% |
| TRL 证据率 | 100% 有证据或人工确认 |
| 向量覆盖率 | 100% |
| Recall@10 | ≥0.70 |
| Precision@5 | ≥0.70 |

## 8. 隐私、许可与公开仓库

1. **模拟数据**：所有模拟需求/企业必须 `is_simulated=true`，`source_note` 写明“团队构造，不对应真实企业”；UI 必须有“模拟数据”标识。
2. **企业名称**：对外展示只用 `display_name` 化名；`legal_name` 不进入前端接口。
3. **联系人**：不采集、不存储手机号、邮箱、微信等个人联系方式。
4. **版权**：OpenAlex 元数据 CC0；摘要可能受出版商版权保护。公开仓库只放截断样例（≤600 字符）和 `source_url`，完整摘要放本地/私有存储。
5. **许可记录**：每条成果记录 `license`；未知写 null，不臆造。
6. **公开仓库**：如仓库继续公开，禁止提交 `data/raw/`、`data/processed/` 全量数据；建议将仓库转为私有，或使用私有数据仓库/对象存储。

## 9. 版本与变更控制

- `dataset_version`：数据版本，如 `v0.1-thin`、`v0.1`、`v0.2`。
- `taxonomy_version`：标签体系版本，如 `v0.1`。
- `embedding_model_version`：模型+维度+预处理版本，如 `bge-m3-1024-v1`。
- 任何字段新增/删除、枚举变更、必填性调整，必须由 PM + DE + AI + BE2 确认，更新本文件并写迁移说明。
- 旧数据不删除；通过 `is_stale` 和版本字段保留追溯。

## 10. 文档口径更正（相对计划书/PRD）

| 项 | 原文档 | 更正 | 处理 |
| --- | --- | --- | --- |
| BGE-M3 维度 | 计划书“BGE-M3 768 维” | **BGE-M3 dense 为 1024 维** | 以本契约和 `数据口径更正记录_v0.1.md` 为准；计划书下次修订改正 |
| 主数据源 | PRD 写“知网/万方/国家知识产权局/arxiv” | **OpenAlex 为主，arXiv 补，CNIPA 可选；CNKI/万方不抓** | 需求规格书/设计报告引用本契约 |
| 成果语言 | PRD 写“中英文混合” | **成果以英文为主；中文展示用机器生成能力画像** | 答辩时说明；不承诺中文论文覆盖 |
| 需求数据 | PRD 写“用户填报” | **演示期 20—30 条公开种子改写 + 70—80 条模拟** | 全部 `is_simulated=true` |
| Python/PostgreSQL | 计划书 Python 3.11 / PostgreSQL 16；过程稿 3.12 / 17 | **以计划书为准：Python 3.11、PostgreSQL 16、pgvector 0.8.x** | 数据脚本兼容 3.11+；BE 迁移按 16 验证 |

## 11. 附：薄切片字段映射示例

```json
{
  "achievement_id": "ach_openalex_W2587767928",
  "source": "openalex",
  "source_id": "W2587767928",
  "doi": "10.1038/natrevmats.2016.103",
  "title_original": "Lithium battery chemistries enabled by solid-state electrolytes",
  "abstract_original": "...",
  "language": "en",
  "publication_year": 2017,
  "type": "review",
  "venue": "Nature Reviews Materials",
  "authors": ["Arumugam Manthiram"],
  "institutions": ["The University of Texas at Austin"],
  "countries": ["US"],
  "keywords": ["solid electrolytes", "all-solid-state lithium batteries"],
  "topics": ["Advanced Battery Materials and Technologies"],
  "cited_by_count": 4872,
  "source_url": "https://doi.org/10.1038/natrevmats.2016.103",
  "license": null,
  "oa_status": "closed",
  "retrieved_at": "2026-11-17T00:00:00Z",
  "content_hash": "...",
  "clean_status": "cleaned",
  "review_status": "pending",
  "quality_flags": ["license_missing"],
  "is_simulated": false,
  "dataset_version": "v0.1-thin"
}
```
