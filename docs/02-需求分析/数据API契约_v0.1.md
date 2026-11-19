# 数据 API 契约 v0.1

> 项目：技术转化智能匹配与产学研对接系统（课题 7，G04）
> 版本：v0.1
> 日期：2026-11-19
> 状态：v0.1，待评审
> 负责人：朱柔璇（BE1）
> 关联文档：`data/spec/data_contract_v0.1.md`、`data/spec/taxonomy_v0.1.md`

## 0. 文档概述

本文档定义科研成果、企业技术需求、标签及匹配结果的数据 API 接口规范，明确前后端数据交互的字段名称、字段类型、请求参数、响应格式及错误处理规则。

本次冲刺主要完成以下四类 API 的字段定义：

1. 科研成果 API（Achievement API）
2. 企业需求 API（Demand API）
3. 标签 API（Tag API）
4. 匹配结果 API（Match API）

本次冲刺不要求完成全部 CRUD 接口、身份认证、实际数据库查询或匹配算法实现。

## 1. 设计原则

1. **字段一致性**：所有 API 字段名称、类型及枚举值以 `data_contract_v0.1.md` 和 `taxonomy_v0.1.md` 为准。
2. **数据格式**：API 采用 JSON 格式，时间字段使用 ISO 8601 标准。
3. **数据安全**：不向前端返回企业真实名称 `legal_name` 或个人敏感信息。
4. **模拟数据标识**：模拟企业与需求必须保留 `is_simulated=true`。
5. **版本管理**：匹配结果必须包含 `dataset_version`、`taxonomy_version` 和 `embedding_model_version`。
6. **字段映射原则**：数据契约规定的数据实体必填字段与 API 响应必返字段不完全等同。API 可根据前端展示需求选择返回字段或聚合关联实体字段，但不得改变原始字段名称、类型、枚举值及业务含义。未返回的字段仍须满足数据契约要求。

## 2. 通用 API 规范

### 2.1 API 基础路径

建议统一使用 `/api/v1` 作为 API 基础路径。

本文档中的接口路径、分页方式及通用响应格式为提出的初步设计方案，需与 BE2、FE 评审确认后正式采用。

### 2.2 通用响应格式

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

失败响应：

```json
{
  "code": 40001,
  "message": "Invalid request parameter",
  "data": null
}
```

其中：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| code | integer | 是 | 业务状态码，0 表示成功 |
| message | string | 是 | 状态描述 |
| data | object / array / null | 是 | 响应数据 |

### 2.3 分页规范

所有列表接口使用以下参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| page | integer | 1 | 当前页码 |
| page_size | integer | 20 | 每页记录数，建议最大 100 |

列表响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 100,
      "total_pages": 5
    }
  }
}
```

### 2.4 错误处理规范

| HTTP 状态码 | 业务码 | 含义 |
|---|---|---|
| 400 | 40001 | 请求参数错误 |
| 401 | 40101 | 未认证 |
| 403 | 40301 | 无访问权限 |
| 404 | 40401 | 数据不存在 |
| 409 | 40901 | 数据冲突 |
| 422 | 42201 | 字段校验失败 |
| 500 | 50001 | 服务器内部错误 |
| 503 | 50301 | 服务暂时不可用 |


## 3. 科研成果 API

### 3.1 接口列表

| 方法 | 接口路径 | 功能 |
|---|---|---|
| GET | `/api/v1/achievements` | 获取成果列表 |
| GET | `/api/v1/achievements/{achievement_id}` | 获取成果详情 |

### 3.2 成果列表接口

**请求方式：** GET

**请求路径：** `/api/v1/achievements`

支持以下筛选参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| page | integer | 页码 |
| page_size | integer | 每页数量 |
| tech_field | string | 技术领域枚举 code |
| publication_year | integer | 发表年份 |
| trl_min | integer | 最低 TRL |
| trl_max | integer | 最高 TRL |
| keyword | string | 标题或技术描述关键词 |


**请求示例：**

`GET /api/v1/achievements?page=1&page_size=20&tech_field=electrolyte`

### 3.3 成果字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| achievement_id | string | 成果唯一标识 |
| title_original | string | 原始标题 |
| publication_year | integer | 发表年份 |
| type | string | 成果类型 |
| source | string | 数据来源 |
| source_url | string | 原始来源链接 |
| language | string | 原文语言 |
| clean_status | string | 数据处理状态 |
| review_status | string | 人工审核状态 |
| is_simulated | boolean | 是否为模拟数据 |
| dataset_version | string | 数据集版本 |

成果详情还需包含：

| 字段 | 类型 | 来源 |
|---|---|---|
| doi | string / null | achievement |
| abstract_original | string | achievement |
| venue | string / null | achievement |
| keywords | array | achievement |
| topics | array | achievement |
| capability_profile_zh | string / null | achievement_text |
| tech_fields | array | achievement_tag |
| application_scenarios | array | achievement_tag |
| trl | integer / null | achievement_extraction |
| trl_evidence | string / null | achievement_extraction |
| key_metrics | array | achievement_extraction |
| ip_status | string | achievement_extraction |

说明：

- `capability_profile_zh` 来源于 `achievement_text`，筛选条件为 `text_type=capability_profile_zh`。
- `tech_fields` 和 `application_scenarios` 由 `achievement_tag` 中对应 `dimension` 的记录组合生成。
- `trl`、`trl_evidence`、`key_metrics` 和 `ip_status` 来源于 `achievement_extraction`。
- 上述字段为 API 聚合展示字段，不代表对原始数据契约新增或修改字段。其响应结构需确认。

### 3.4 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "achievement_id": "ach_openalex_W123456",
    "title_original": "Example Battery Materials Research",
    "publication_year": 2024,
    "type": "article",
    "source": "openalex",
    "source_url": "https://openalex.org/W123456",
    "language": "en",
    "capability_profile_zh": "该成果研究电池材料的性能优化方法。",
    "tech_fields": [
      {
        "code": "electrolyte",
        "is_primary": true
      }
    ],
    "trl": 3,
    "trl_evidence": "lab-scale experimental validation",
    "ip_status": "unknown",
    "is_simulated": false,
    "dataset_version": "v0.1"
  }
}
```

注：此处数据仅用于说明响应结构，不代表真实科研成果或实际抽取结果。

## 4. 企业需求 API

### 4.1 接口列表

| 方法 | 接口路径 | 功能 |
|---|---|---|
| GET | `/api/v1/demands` | 获取需求列表 |
| GET | `/api/v1/demands/{demand_id}` | 获取需求详情 |

### 4.2 需求列表筛选参数

| 参数 | 类型 | 说明 |
|---|---|---|
| page | integer | 页码 |
| page_size | integer | 每页数量 |
| tech_field | string | 技术领域 |
| required_trl | integer | 按需求最低可接受 TRL 精确筛选，取值范围 1–9。例如 required_trl=5 仅返回该字段等于 5 的需求。 |
| region | string | 意向地区 |
| status | string | 需求状态 |
| cooperation_mode | string | 合作模式 |

筛选规则说明：

required_trl 表示企业需求可接受的最低技术成熟度。API 列表筛选采用精确匹配，即仅返回 required_trl 与查询参数相等的需求。该筛选方式为建议方案。

### 4.3 需求字段定义

| 字段                    | 类型 | 必填（数据契约） | 说明        |
|-----------------------|---|---|-----------|
| demand_id             | string | 是 | 需求 ID     |
| enterprise_id         | string | 是 | 所属企业 ID   |
| title                 | string | 是 | 需求标题      |
| pain_point            | string | 是 | 技术痛点      |
| expected_solution     | string | 是 | 期望解决方案    |
| technical_metrics     | array | 是 | 技术指标      |
| budget_range          | string / null | 否 | 预算范围      |
| timeline              | string / null | 否 | 预计周期      |
| cooperation_modes     | array | 是 | 合作方式      |
| required_trl          | integer | 是 | 最低可接受 TRL |
| tech_fields           | array | 是 | 技术领域      |
| application_scenarios | array | 是 | 应用场景      |
| ip_requirement        | string / null | 否 | 知识产权要求    |
| region                | string | 是 | 意向地区      |
| status                | string | 是 | 需求状态      |
| valid_until           | string | 是 | 有效期       |
| is_simulated          | boolean | 是 | 是否为模拟数据   |
| source_note           | string | 是 | 数据来源说明    |
| dataset_version       | string | 是 | 数据版本      |

**API 聚合展示字段：**

为满足前端需求列表和详情页的展示要求，需求 API 可通过 `enterprise_id` 关联 `enterprise` 实体，返回企业化名。

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| enterprise_display_name | string | `enterprise.display_name` | 所属企业化名，用于前端展示 |

`enterprise_display_name` 为 API 派生字段，不属于 `demand` 实体的原始字段，不修改现有数据契约。该字段及其返回方式需确认。API 不返回企业真实名称 `legal_name`。

### 4.4 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "demand_id": "dem_005",
    "enterprise_id": "ent_001",
    "enterprise_display_name": "某动力电池企业",
    "title": "硫化物固态电解质中试放大",
    "pain_point": "现有电解质工艺难以满足规模化生产要求。",
    "expected_solution": "寻找具有中试放大能力的固态电解质技术。",
    "technical_metrics": [
      {
        "name": "室温离子电导率",
        "value": ">=10",
        "unit": "mS/cm"
      }
    ],
    "cooperation_modes": ["joint_rd", "joint_lab"],
    "required_trl": 5,
    "tech_fields": ["electrolyte"],
    "application_scenarios": ["ev_power"],
    "region": "any",
    "status": "active",
    "valid_until": "2027-12-31",
    "is_simulated": true,
    "source_note": "团队构造，不对应真实企业",
    "dataset_version": "v0.1"
  }
}
```

注：示例是演示性模拟需求。

## 5. 标签 API

### 5.1 接口列表

| 方法 | 接口路径 | 功能 |
|---|---|---|
| GET | `/api/v1/taxonomy` | 获取标签枚举 |
| GET | `/api/v1/achievements/{achievement_id}/tags` | 获取成果标签 |
| GET | `/api/v1/demands/{demand_id}/tags` | 获取需求标签 |

### 5.2 标签字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| tag_id | string | 标签记录唯一 ID |
| achievement_id / demand_id | string | 所属对象 ID |
| dimension | string | 标签维度 |
| code | string | 枚举编码 |
| is_primary | boolean | 是否为主标签 |
| confidence | number | 模型置信度，0–1 |
| evidence | string / null | 证据片段 |
| method | string | 生成方式 |
| model | string / null | 提取模型 |
| prompt_version | string / null | Prompt 版本 |
| review_status | string | 审核状态 |
| created_at | string (ISO 8601) | 标签创建时间，来源于数据契约中的 created_at 字段 |

需求标签遵循 `demand_tag` 字段口径。

### 5.3 技术领域枚举

| code | 中文名称 |
|---|---|
| cathode_material | 正极材料 |
| anode_material | 负极材料 |
| electrolyte | 电解质 |
| separator | 隔膜 |
| cell_system | 电芯与系统 |
| recycling | 回收与梯次利用 |
| flow_battery | 液流电池 |
| supercapacitor | 超级电容器 |

`achievement_tag.dimension` 仅允许以下三个枚举值：

- `tech_field`
- `application_scenario`
- `cooperation_mode`

此外，标签体系还定义了 `trl`、`ip_status`、`target_region` 和 `target_industry` 等辅助属性，但这些属性不属于 `achievement_tag.dimension` 的可选值。

所有枚举及约束以 `taxonomy_v0.1.md` 和 `data_contract_v0.1.md` 为准。

### 5.4 标签响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "achievement_id": "ach_openalex_W123456",
    "tags": [
      {
        "tag_id": "tag_001",
        "dimension": "tech_field",
        "code": "electrolyte",
        "is_primary": true,
        "confidence": 0.93,
        "evidence": "sulfide solid electrolyte",
        "method": "llm",
        "model": "qwen3.8-flash",
        "review_status": "pending",
        "created_at": "2026-11-19T08:00:00Z"
      }
    ]
  }
}
```

### 5.5 标签约束

1. 每条科研成果至少具有 1 个、最多 2 个 `tech_field` 标签，且必须恰好有 1 个 `is_primary=true` 的主标签。
2. 每条科研成果最多包含 3 个 `application_scenario` 标签。
3. `confidence` 取值范围为 0–1。
4. 标签的 `dimension` 和 `code` 必须符合 `taxonomy_v0.1.md`。
5. 无充分证据时不得编造标签，需按照数据契约及标签体系中的未知值与人工复核规则处理。
6. 需求侧 `tech_field` 为 1–2 个，`cooperation_mode` 为 1–3 个。

## 6. 匹配结果 API

### 6.1 接口列表

| 方法 | 接口路径 | 功能 |
|---|---|---|
| GET | `/api/v1/demands/{demand_id}/matches` | 根据需求获取推荐成果 |
| GET | `/api/v1/achievements/{achievement_id}/matches` | 根据成果获取适配需求 |
| GET | `/api/v1/matches/{match_id}` | 获取匹配详情 |

本冲刺仅定义字段和响应结构，不实现完整匹配引擎。

### 6.2 匹配结果列表查询参数

匹配结果列表接口支持以下分页及过滤参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| page | integer | 1 | 当前页码 |
| page_size | integer | 20 | 每页记录数，最大 100 |
| min_score | number | 0 | 最低匹配总分（`total_score`），范围 0–100 |
| is_stale | boolean | false | 按匹配结果失效状态筛选；false 仅返回有效结果，true 仅返回失效结果 |

**请求示例：**

`GET /api/v1/demands/{demand_id}/matches?page=1&page_size=20&min_score=70&is_stale=false`

匹配结果列表统一采用第 2.3 节定义的分页响应格式，返回 `items` 和 `pagination`。默认按 `total_score` 降序排列。

以上查询参数及排序规则为建议方案，需评审确认。

### 6.3 匹配结果字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| match_id | string | 是 | 匹配 ID |
| achievement_id | string | 是 | 成果 ID |
| demand_id | string | 是 | 需求 ID |
| total_score | number | 是 | 适配度，0–100 |
| tag_score | number | 是 | 标签分数，0–100 |
| semantic_score | number | 是 | 语义分数，0–100 |
| llm_score | number / null | 否 | LLM 精排分数 |
| reason | string | 是 | 推荐理由 |
| risk | object | 是 | 四维风险 |
| evidence | object | 是 | 匹配证据 |
| model | string | 是 | 模型 |
| prompt_version | string | 是 | Prompt 版本 |
| dataset_version | string | 是 | 数据版本 |
| taxonomy_version | string | 是 | 标签体系版本 |
| embedding_model_version | string | 是 | 向量模型版本 |
| is_stale | boolean | 是 | 是否失效 |
| created_at | string | 是 | 创建时间 |

### 6.4 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "match_id": "match_001",
    "achievement_id": "ach_openalex_W123456",
    "demand_id": "dem_005",
    "total_score": 86.5,
    "tag_score": 90.0,
    "semantic_score": 83.0,
    "llm_score": null,
    "reason": "成果技术方向与企业需求一致，具备潜在合作价值。",
    "risk": {
      "technical": null,
      "market": null,
      "ip": null,
      "collaboration": null
    },
    "evidence": {},
    "model": "example-reranker",
    "prompt_version": "example-prompt-v1",
    "dataset_version": "v0.1",
    "taxonomy_version": "v0.1",
    "embedding_model_version": "qwen3.7-text-embedding-flash-1024-v1",
    "is_stale": false,
    "created_at": "2026-11-19T08:00:00Z"
  }
}
```

注：此示例仅说明结构。评分、风险、模型版本及其他值均为演示数据，实际取值由后续匹配引擎和数据库记录确定。model、prompt_version、is_stale 等字段在正式实现时必须使用真实运行记录，不得将示例占位值作为实际匹配结果入库。`risk` 内部键名是待评审的接口结构，不代表当前数据契约已冻结该 JSON 子结构。

### 6.5 版本一致性

匹配结果必须绑定以下三个版本：

- `dataset_version`
- `taxonomy_version`
- `embedding_model_version`

当任一版本变化时，旧匹配结果应标记 `is_stale=true`，重新计算后才能作为有效推荐展示。

`total_score` 表示技术适配度，不代表合作成交概率。

## 7. 数据安全与隐私

### 7.1 企业信息保护

- 对外只返回 `display_name`，不返回 `legal_name`。
- 不采集或展示联系人电话、电子邮箱、微信等个人信息。
- 模拟需求与企业必须带有 `is_simulated=true`。
- 前端应明确显示“模拟数据”标识。

### 7.2 科研成果版权

OpenAlex 元数据可以用于项目，但科研摘要可能受出版商版权保护。

公开仓库中的样例摘要正文不得超过 600 字符，截断时添加省略号。完整摘要仅放在本地或私有存储。

正式 API 的全文访问权限及展示策略需在后续实现阶段确认，不能将“仓库样例长度限制”直接等同于所有 API 返回内容的限制。

### 7.3 字段与枚举变更

任何新增、删除字段或修改枚举值的请求，必须按照项目变更控制流程由 PM、DE、AI、BE2 确认。

## 8. 版本记录

| 版本 | 变更内容 | 负责人 |
|---|---|---|
| v0.1 | 初版：成果、需求、标签、匹配结果 API 字段契约及通用接口规范 | 朱柔璇 |
