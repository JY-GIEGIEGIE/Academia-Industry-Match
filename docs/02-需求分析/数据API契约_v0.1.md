# 数据 API 契约 v0.1

> 项目：技术转化智能匹配与产学研对接系统（课题 7，G04）
> 版本：v0.1
> 日期：2026-11-21
> 状态：v0.1，评审补全版（待 FE/BE 联调确认）
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

**成果摘要 `achievement_summary`（成果列表项；匹配列表复用同一结构）：**

| 字段 | 类型 | 说明 |
|---|---|---|
| achievement_id | string | 成果唯一标识 |
| title_original | string | 原始标题 |
| abstract_preview | string / null | 摘要预览，取自 `abstract_original`，最多 300 字符，截断加省略号；无摘要为 `null` |
| capability_profile_zh | string / null | 中文能力画像，机器生成；无则 `null`，不得替代 `abstract_original` 作为证据 |
| publication_year | integer | 发表年份 |
| type | string | 成果类型 |
| source | string | 数据来源 |
| source_url | string | 原始来源链接 |
| language | string | 原文语言 |
| trl | integer / null | 技术成熟度 1—9；无证据为 `null` |
| tech_fields | array | 技术领域标签，元素为 `{code, is_primary}` |
| application_scenarios | array | 应用场景 code 数组 |
| is_simulated | boolean | 是否为模拟数据 |
| dataset_version | string | 数据集版本 |

> `abstract_preview` 只用于列表卡片；详情接口返回完整 `abstract_original`。`tech_fields` / `application_scenarios` 的 code 中文 label 由 `/api/v1/taxonomy` 提供。

成果详情在摘要字段基础上增加：

| 字段 | 类型 | 来源 |
|---|---|---|
| doi | string / null | achievement |
| abstract_original | string | achievement |
| venue | string / null | achievement |
| keywords | array | achievement |
| topics | array | achievement |
| clean_status | string | achievement |
| review_status | string | achievement |
| trl_evidence | string / null | achievement_extraction |
| key_metrics | array | achievement_extraction |
| material_system | string / null | achievement_extraction |
| process | array | achievement_extraction |
| ip_status | string | achievement_extraction |

说明：

- `achievement_summary` 是 API 聚合结构，不是新的持久化实体。
- `tech_fields` 元素结构为 `{"code": "electrolyte", "is_primary": true}`，`code` 来自 `taxonomy_v0.1.md`；每条成果恰好一个 `is_primary=true`。
- `application_scenarios` 是 code 数组，例如 `["ev_power"]`；最多 3 个。
- `trl` 的显示标签（如“4 实验室器件”）由 `/api/v1/taxonomy` 的 `trl` 维度提供。
- `capability_profile_zh` 来源于 `achievement_text`，筛选条件为 `text_type=capability_profile_zh`；机器生成文本，原文证据仍以 `abstract_original` 为准。
- `trl_evidence`、`key_metrics` 和 `ip_status` 来源于 `achievement_extraction`。
- `key_metrics` 元素结构为 `{"name","value","unit","evidence"}`；无 `evidence` 的指标不得作为结论展示。
- `material_system` 和 `process` 来源于 `achievement_extraction`；无证据写 `null` / 空数组，不编造。
- `achievement_summary` 中的 `tech_fields` 只含 `code` / `is_primary`；需要 `confidence` / `evidence` 时调用 tags API。

### 3.4 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "achievement_id": "ach_openalex_W123456",
    "title_original": "Example Battery Materials Research",
    "abstract_preview": "This work studies the performance optimization of battery materials using ...",
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
    "application_scenarios": ["ev_power"],
    "trl": 3,
    "trl_evidence": "lab-scale experimental validation",
    "ip_status": "unknown",
    "is_simulated": false,
    "dataset_version": "v0.1"
  }
}
```

注：以上为成果详情示例；列表接口返回 §3.3 的 `achievement_summary` 字段。示例数据仅用于说明响应结构，不代表真实科研成果或实际抽取结果。

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
| cooperation_mode | string | 合作模式 code；匹配 demand.cooperation_modes 包含该 code 的需求 |

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
| technical_metrics     | array | 是 | 技术指标；元素结构为 {name,value,unit} |
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

为满足前端需求列表和详情页的展示要求，需求 API 通过 `enterprise_id` 关联 `enterprise` 实体，返回企业摘要 `enterprise` 对象：

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| enterprise | object | `enterprise` | 企业摘要，不包含 `legal_name`、联系人等敏感信息 |
| enterprise.display_name | string | `enterprise.display_name` | 企业化名，用于前端展示 |
| enterprise.industry | string | `enterprise.industry` | 企业行业枚举 code |
| enterprise.size | string | `enterprise.size` | 企业规模枚举 code：`large` / `medium` / `small` |

`enterprise` 为 API 聚合对象，不属于 `demand` 实体的原始字段，不修改现有数据契约；原 `enterprise_display_name` 由 `enterprise.display_name` 替代，不再单独返回。API 不返回企业真实名称 `legal_name`。兼容性说明：v0.1 初版曾返回 `enterprise_display_name`；本版改为 `enterprise.display_name`，FE 以本版为准。

需求列表和匹配列表中的 `demand_summary` 至少包含：`demand_id`、`enterprise_id`、`title`、`pain_point`、`required_trl`、`tech_fields`、`application_scenarios`、`is_simulated`、`dataset_version` 和 `enterprise`；详情接口返回完整字段。

### 4.4 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "demand_id": "dem_005",
    "enterprise_id": "ent_001",
    "enterprise": {
      "display_name": "某动力电池企业",
      "industry": "battery_manufacturing",
      "size": "large"
    },
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

注：以上为需求详情示例；列表接口返回 §4.3 的 `demand_summary` 字段。示例是演示性模拟需求。

## 5. 标签与枚举 API

### 5.1 接口列表

| 方法 | 接口路径 | 功能 |
|---|---|---|
| GET | `/api/v1/taxonomy` | 获取标签与筛选/展示枚举 |
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

### 5.3 枚举响应

`GET /api/v1/taxonomy` 返回前端筛选和展示所需的全部枚举；可选查询参数 `dimension` 用于只取一个维度，例如 `?dimension=tech_field`。

响应结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "taxonomy_version": "v0.1",
    "dimensions": [
      {
        "dimension": "tech_field",
        "label": "技术领域",
        "type": "enum",
        "applies_to": ["achievement", "demand"],
        "values": [
          {"code": "cathode_material", "label": "正极材料"},
          {"code": "anode_material", "label": "负极材料"},
          {"code": "electrolyte", "label": "电解质"},
          {"code": "separator", "label": "隔膜"},
          {"code": "cell_system", "label": "电芯与系统"},
          {"code": "recycling", "label": "回收与梯次利用"},
          {"code": "flow_battery", "label": "液流电池"},
          {"code": "supercapacitor", "label": "超级电容器"}
        ]
      },
      {
        "dimension": "trl",
        "label": "技术成熟度",
        "type": "ordinal",
        "applies_to": ["achievement", "demand"],
        "values": [
          {"code": "1", "label": "1 基本原理"},
          {"code": "2", "label": "2 技术概念"},
          {"code": "3", "label": "3 实验室验证"},
          {"code": "4", "label": "4 实验室器件"},
          {"code": "5", "label": "5 相关环境验证/中试"},
          {"code": "6", "label": "6 原型演示"},
          {"code": "7", "label": "7 实际环境演示"},
          {"code": "8", "label": "8 系统定型"},
          {"code": "9", "label": "9 商业运行"}
        ]
      }
    ]
  }
}
```

完整维度如下（示例只展开 `tech_field` 和 `trl`，其余维度按同一结构返回）：

| dimension | label | type | applies_to | 值来源 |
|---|---|---|---|---|
| `tech_field` | 技术领域 | enum | achievement, demand | taxonomy §2，8 个值 |
| `application_scenario` | 应用场景 | enum | achievement, demand | taxonomy §3，8 个值 |
| `cooperation_mode` | 合作模式 | enum | achievement, demand | taxonomy §5，5 个值 |
| `ip_status` | 知识产权状态 | enum | achievement | taxonomy §6.1，4 个值 |
| `region` | 意向地区 | enum | demand, enterprise | taxonomy §6.2（`target_region`），6 个值 |
| `industry` | 企业行业 | enum | demand, enterprise | taxonomy §6.3（`target_industry`），6 个值 |
| `enterprise_size` | 企业规模 | enum | enterprise, demand | data_contract `enterprise.size`，3 个值 |
| `status` | 需求状态 | enum | demand | data_contract `demand.status`，4 个值 |
| `language` | 语言 | enum | achievement | data_contract `achievement.language`，4 个值 |
| `type` | 成果类型 | enum | achievement | data_contract `achievement.type`，5 个值 |
| `trl` | 技术成熟度 | ordinal | achievement, demand | taxonomy §4，1—9 级 |

API 补充枚举的 label（taxonomy 未单列的 4 组）：

| dimension | values |
|---|---|
| `enterprise_size` | `large` 大型、`medium` 中型、`small` 小型 |
| `status` | `draft` 草稿、`active` 生效、`expired` 已过期、`closed` 已关闭 |
| `language` | `en` 英文、`zh` 中文、`mixed` 中英混合、`unknown` 未知 |
| `type` | `article` 期刊论文、`review` 综述、`preprint` 预印本、`patent` 专利、`other` 其他 |

说明：

- `region` 对应 taxonomy 中的 `target_region`，`industry` 对应 `target_industry`；API 统一使用 `region` / `industry` 字段名。
- `dimensions` 必须包含上表全部 11 个维度，每个 `values` 必须覆盖对应枚举全集；只返回 `tech_field` 视为契约未实现。
- `values` 顺序固定，FE 不应硬编码；`label` 由后端返回，前端不得自行维护中文映射。
- `taxonomy_version` 必须返回；枚举或 label 变化时升级版本，FE 用它判断缓存是否失效。
- `dimension` 只允许上表中的值，未知值返回 `40001`。
- `achievement_tag.dimension` 仍只允许 `tech_field`、`application_scenario`、`cooperation_mode` 三个值；其余维度是 API 筛选/展示用枚举，不是标签表的维度。

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

### 6.3 匹配列表字段

匹配列表接口（`/demands/{demand_id}/matches`、`/achievements/{achievement_id}/matches`）的 `items[]` 返回：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| match_id | string | 是 | 匹配 ID |
| total_score | number | 是 | 适配度，0–100 |
| tag_score | number | 是 | 标签分数，0–100 |
| semantic_score | number | 是 | 语义分数，0–100 |
| llm_score | number / null | 否 | LLM 精排分数 |
| risk_overall_score | integer / null | 否 | 列表卡片用的综合风险分，1=低风险，5=高风险；不返回四维详情 |
| reason | string | 是 | 推荐理由 |
| achievement_summary | object | 是 | 成果摘要，结构见 §3.3；不含作者/机构 |
| demand_summary | object | 是 | 需求摘要，结构见 §4.3；含 `enterprise` 对象 |
| is_stale | boolean | 是 | 是否失效 |
| created_at | string (ISO 8601) | 是 | 创建时间 |

说明：

- 列表只返回卡片展示所需字段；完整 `risk`、`evidence`、模型版本信息只在 `GET /api/v1/matches/{match_id}` 详情返回，避免列表响应过大。
- `achievement_summary` / `demand_summary` 使用 §3.3 / §4.3 的列表字段；FE 一次列表请求即可渲染推荐卡片，不需要 N+1 请求详情。
- 如果列表需要风险徽标，可在 `achievement_summary` 之外增加轻量 `risk_overall_score`（1—5，可空），但不要返回四维详情。

### 6.4 匹配详情字段与 `risk` / `evidence` 结构

`GET /api/v1/matches/{match_id}` 在 §6.3 列表字段基础上增加：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| risk | object / null | 是 | 四维风险；`is_stale=true` 或未精排时为 `null` |
| evidence | object / null | 是 | 匹配证据；`is_stale=true` 或未精排时为 `null` |
| model | string | 是 | 精排模型名称/版本 |
| prompt_version | string | 是 | 精排 Prompt 版本 |
| dataset_version | string | 是 | 数据版本 |
| taxonomy_version | string | 是 | 标签体系版本 |
| embedding_model_version | string | 是 | 向量模型版本 |

#### `risk` 结构

```json
{
  "risk": {
  "technical": {
    "score": 4,
    "description": "成果 TRL 4，低于需求要求 TRL 5，需中试验证。"
  },
  "market": {
    "score": 2,
    "description": "应用场景与企业主营动力电池匹配。"
  },
  "ip": {
    "score": 3,
    "description": "论文未披露专利状态，IP 证据不足。"
  },
  "collaboration": {
    "score": 3,
    "description": "合作模式兼容，但企业规模偏小。"
  },
  "overall": {
    "summary": "技术方向匹配，主要风险在中试放大和 IP 状态。",
    "mitigation": [
      "先做中试可行性验证",
      "开展 IP 尽调并签署保密协议"
    ]
  }
}
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| risk.technical / market / ip / collaboration | object | 是 | 四个风险维度，分别对应 PRD §6.5 |
| risk.<dimension>.score | integer 1—5 | 是 | 风险程度：**1=低风险，5=高风险** |
| risk.<dimension>.description | string | 是 | 一句话说明，必须对应评估依据 |
| risk.overall | object | 是 | 综合风险提示与规避建议 |
| risk.overall.summary | string | 是 | 大模型生成的综合风险提示 |
| risk.overall.mitigation | string[] | 是 | 1—3 条可执行规避建议 |

说明：

- 技术风险依据：成果 TRL 与需求 `required_trl` 的差距、技术路线兼容性。
- 市场风险依据：成果 `application_scenarios` 与企业主营/行业匹配度。
- 知识产权风险依据：`ip_status`、专利状态与权利清晰度；论文默认 `unknown`，不得编造。
- 合作风险依据：地区距离、合作模式偏好冲突、企业规模匹配度。
- `risk=null` 只允许出现在 `is_stale=true` 或尚未完成精排的记录。前端必须区分两种状态：`is_stale=true` 显示“待重算”，仅尚未完成精排显示“待精排/评估”；不能把 null 当成有效风险。

#### `evidence` 结构

```json
{
  "evidence": {
  "tag_matches": [
    {
      "dimension": "tech_field",
      "code": "electrolyte",
      "achievement_confidence": 0.93,
      "demand_confidence": 0.88
    }
  ],
  "snippets": [
    {
      "side": "achievement",
      "field": "abstract_original",
      "text": "Sulfide solid electrolytes were scaled up to pilot-scale cells ...",
      "source_ref": "achievement.abstract_original"
    },
    {
      "side": "demand",
      "field": "pain_point",
      "text": "现有电解质工艺难以满足规模化生产要求。",
      "source_ref": "demand.pain_point"
    }
  ],
  "metric_matches": [
    {
      "name": "室温离子电导率",
      "achievement_value": "12",
      "required_value": ">=10",
      "unit": "mS/cm",
      "matched": true
    }
  ]
}
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| evidence.tag_matches | array | 否 | 命中的成果/需求标签 |
| evidence.tag_matches[].dimension | string | 是 | `tech_field` / `application_scenario` / `cooperation_mode` |
| evidence.tag_matches[].code | string | 是 | taxonomy 枚举 code |
| evidence.tag_matches[].achievement_confidence | number | 否 | 成果标签置信度 0—1 |
| evidence.tag_matches[].demand_confidence | number | 否 | 需求标签置信度 0—1 |
| evidence.snippets | array | 否 | 原文摘录；机器画像只能作补充 |
| evidence.snippets[].side | enum(`achievement`/`demand`) | 是 | 证据所属一侧 |
| evidence.snippets[].field | string | 是 | 展示字段，如 `abstract_original`、`pain_point` |
| evidence.snippets[].text | string | 是 | 摘录，建议 ≤200 字符 |
| evidence.snippets[].source_ref | string | 是 | 可追溯来源，如 `achievement.abstract_original` |
| evidence.metric_matches | array | 否 | 指标对比 |
| evidence.metric_matches[].name | string | 是 | 指标名称 |
| evidence.metric_matches[].achievement_value | string / number | 否 | 成果指标值 |
| evidence.metric_matches[].required_value | string | 否 | 需求指标要求 |
| evidence.metric_matches[].unit | string | 否 | 单位 |
| evidence.metric_matches[].matched | boolean | 否 | 是否满足需求 |

说明：

- `is_stale=false` 时，`tag_matches`、`snippets`、`metric_matches` 至少有一项非空；否则 `evidence=null`，`reason` 不能编造证据。
- `source_ref` 必须能定位到数据表/字段：标签来自 `achievement_tag` / `demand_tag`，文本来自 `achievement_text` / `abstract_original` / `demand.pain_point`，指标来自 `achievement_extraction.key_metrics` 与需求 `technical_metrics`。
- `capability_profile_zh` 等机器生成文本不得作为唯一证据；如需展示，必须同时提供 `abstract_original` 原文片段。
- `risk` / `evidence` 的字段结构以 `data/spec/data_contract_v0.1.md` §4.10 为准；本节提供响应示例与字段展开，两处必须同步变更。

### 6.5 响应示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "match_id": "match_001",
    "total_score": 86.5,
    "tag_score": 90.0,
    "semantic_score": 83.0,
    "llm_score": null,
    "reason": "成果技术方向与企业需求一致，具备潜在合作价值。",
    "achievement_summary": {
      "achievement_id": "ach_openalex_W123456",
      "title_original": "Example Battery Materials Research",
      "abstract_preview": "This work studies the performance optimization of battery materials ...",
      "capability_profile_zh": "该成果研究电池材料的性能优化方法。",
      "publication_year": 2024,
      "type": "article",
      "source": "openalex",
      "source_url": "https://openalex.org/W123456",
      "language": "en",
      "trl": 4,
      "tech_fields": [
        {"code": "electrolyte", "is_primary": true}
      ],
      "application_scenarios": ["ev_power"],
      "is_simulated": false,
      "dataset_version": "v0.1"
    },
    "demand_summary": {
      "demand_id": "dem_005",
      "enterprise_id": "ent_001",
      "title": "硫化物固态电解质中试放大",
      "pain_point": "现有电解质工艺难以满足规模化生产要求。",
      "expected_solution": "寻找具有中试放大能力的固态电解质技术。",
      "technical_metrics": [
        {"name": "室温离子电导率", "value": ">=10", "unit": "mS/cm"}
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
      "dataset_version": "v0.1",
      "enterprise": {
        "display_name": "某动力电池企业",
        "industry": "battery_manufacturing",
        "size": "large"
      }
    },
    "risk": {
      "technical": {
        "score": 4,
        "description": "成果 TRL 4，低于需求要求 TRL 5，需中试验证。"
      },
      "market": {
        "score": 2,
        "description": "应用场景与企业主营动力电池匹配。"
      },
      "ip": {
        "score": 3,
        "description": "论文未披露专利状态，IP 证据不足。"
      },
      "collaboration": {
        "score": 3,
        "description": "合作模式兼容，但企业规模偏小。"
      },
      "overall": {
        "summary": "技术方向匹配，主要风险在中试放大和 IP 状态。",
        "mitigation": [
          "先做中试可行性验证",
          "开展 IP 尽调并签署保密协议"
        ]
      }
    },
    "evidence": {
      "tag_matches": [
        {
          "dimension": "tech_field",
          "code": "electrolyte",
          "achievement_confidence": 0.93,
          "demand_confidence": 0.88
        }
      ],
      "snippets": [
        {
          "side": "achievement",
          "field": "abstract_original",
          "text": "Sulfide solid electrolytes were scaled up to pilot-scale cells ...",
          "source_ref": "achievement.abstract_original"
        },
        {
          "side": "demand",
          "field": "pain_point",
          "text": "现有电解质工艺难以满足规模化生产要求。",
          "source_ref": "demand.pain_point"
        }
      ],
      "metric_matches": [
        {
          "name": "室温离子电导率",
          "achievement_value": "12",
          "required_value": ">=10",
          "unit": "mS/cm",
          "matched": true
        }
      ]
    },
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

注：评分、风险、模型版本及其他值均为演示数据，实际取值由匹配引擎和数据库记录确定。`model`、`prompt_version`、`is_stale` 等字段在正式实现时必须使用真实运行记录，不得将示例占位值作为实际匹配结果入库。

### 6.6 版本一致性

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
| v0.1（2026-11-21） | 评审补全：定义 risk/evidence 子结构、taxonomy 完整响应、列表聚合字段 | 朱柔璇（原稿）、贾越（评审补全） |
