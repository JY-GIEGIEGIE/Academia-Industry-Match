# 标签体系 v0.1

> 项目：技术转化智能匹配与产学研对接系统（课题 7，G04）
> 版本：v0.1
> 日期：2026-11-17
> 状态：v0.1，第一次冲刺使用；20 条双人标注用于校准，枚举变更走变更控制
> 负责人：黄欣悦（DE）、陈镇灏（AI）
> 关联：`data_contract_v0.1.md`

## 0. 设计原则

1. **枚举可控**：每个维度 5—8 个值；LLM 只能映射，不得自由生成标签。
2. **互斥可判定**：同一维度内的值尽量互斥；跨维度允许组合（如“固态电解质 + 动力电池 + TRL 5”）。
3. **有证据才标**：每个标签必须能指向原文片段；无依据写 `unknown`，不猜。
4. **主标签唯一**：`tech_field` 每个成果恰好一个 `is_primary=true`；跨领域成果用主标签+次标签表达。
5. **版本化**：任何枚举调整升级 `taxonomy_version`，旧数据保留原版本，不静默覆盖。

## 1. 维度总览

| 维度 | 用途 | 取值数 | 是否硬过滤 |
| --- | --- | ---: | --- |
| `tech_field` | 技术领域/材料环节 | 8 | 是（默认同领域；跨领域需显式勾选） |
| `application_scenario` | 应用场景 | 8 | 软过滤/加权 |
| `trl` | 技术成熟度 | 1—9 | 软约束（需求 `required_trl` vs 成果 `trl`） |
| `cooperation_mode` | 合作模式 | 5 | 软约束/风险项 |
| `ip_status` | 知识产权状态 | 4 | 风险项 |
| `target_region` | 意向地区 | 6 | 软约束 |
| `target_industry` | 目标行业 | 6 | 软约束 |

## 2. `tech_field`（技术领域）

| code | 中文 | 定义 | 包含 | 不包含 |
| --- | --- | --- | --- | --- |
| `cathode_material` | 正极材料 | 正极活性材料及其改性、合成、包覆、掺杂 | NCM/NCA、LFP/LMFP、富锂锰基、钠电正极、钴酸锂 | 电解质、隔膜、电芯制造 |
| `anode_material` | 负极材料 | 负极活性材料及其改性、合成 | 石墨、硅碳/硅氧、硬碳、锂金属、钛酸锂 | 集流体、电芯 |
| `electrolyte` | 电解质 | 液态/固态/凝胶电解质、添加剂、离子导体 | 硫化物、氧化物、聚合物、卤化物、复合电解质 | 隔膜（单独一类） |
| `separator` | 隔膜 | 隔离正负极的多孔膜及涂覆 | PE/PP、陶瓷涂覆、PMMA/PVDF 涂覆、无纺布 | 电解质 |
| `cell_system` | 电芯与系统 | 电芯设计、制造工艺、模组/PACK、热管理、BMS、安全 | 热失控、热管理、快充、成组、BMS | 材料级研究 |
| `recycling` | 回收与梯次利用 | 退役电池回收、材料再生、梯次利用 | 湿法/火法/直接再生、分选、SOH 评估 | 新材制造 |
| `flow_battery` | 液流电池 | 液流电池材料、电堆与系统 | 全钒、铁铬、锌基、有机液流 | 锂离子电池 |
| `supercapacitor` | 超级电容器 | 双电层/赝电容材料与器件 | 活性炭、石墨烯、MXene、导电聚合物 | 电池 |

**主/次标签规则**：

- 一个成果至少 1 个 `tech_field`，最多 2 个；恰好 1 个 `is_primary=true`。
- 固态电池这类交叉成果：按“核心创新点”定主标签。例如“硫化物电解质”主标签 `electrolyte`，次标签 `anode_material`（若同时解决锂金属界面）。
- 跨领域匹配（如液流 vs 锂电）默认不进入候选；管理员/用户显式勾选“跨领域”后才放开。

## 3. `application_scenario`（应用场景）

| code | 中文 | 说明 |
| --- | --- | --- |
| `ev_power` | 动力电池 | 电动汽车、商用车、船舶/航空动力 |
| `grid_storage` | 电网储能 | 发电侧、电网侧、调峰调频 |
| `cni_storage` | 工商业储能 | 园区、数据中心、工商业峰谷套利 |
| `residential_storage` | 户用储能 | 家庭光储、便携储能 |
| `consumer_electronics` | 消费电子 | 手机、笔电、穿戴、无人机 |
| `e_tool_two_wheeler` | 电动工具/两轮车 | 电动工具、电助力车、电动两轮车 |
| `special` | 特种应用 | 航空航天、军工、极寒/深海等 |
| `recycling_industry` | 回收产业 | 退役电池回收、再生材料、梯次利用 |

一个成果最多 3 个场景；需求 1—3 个；无法判断写 `unknown`（不进入枚举，作为标签缺失处理）。

## 4. `trl`（技术成熟度）

| TRL | 名称 | 判定口径 | 文本证据示例 | 论文/专利典型信号 |
| ---: | --- | --- | --- | --- |
| 1 | 基本原理 | 只有基础原理/计算/假设 | “first-principles”“DFT”“proof of concept” | 计算、机理类论文 |
| 2 | 技术概念 | 形成技术概念/应用设想 | “conceptual design”“proposed mechanism” | 综述/概念论文 |
| 3 | 实验室验证 | 实验室小样验证关键功能 | “synthesized”“coin cell”“lab-scale” | 材料合成、纽扣电池 |
| 4 | 实验室器件 | 可重复的实验室器件/小软包 | “pouch cell”“prototype”“repeatable” | 小软包、器件级 |
| 5 | 相关环境验证/中试 | 中试线、放大工艺、Ah 级 | “pilot-scale”“scale-up”“Ah-level” | 中试、放大工艺 |
| 6 | 原型演示 | 原型系统在相关环境演示 | “module”“pack-level”“demonstrator” | 模组/PACK 原型 |
| 7 | 实际环境演示 | 实际场景演示 | “field test”“real-world”“vehicle demo” | 装车/现场测试 |
| 8 | 系统定型 | 系统完成定型/认证 | “certified”“production-ready” | 认证、定型 |
| 9 | 商业运行 | 商业化稳定运行 | “commercial”“mass production” | 量产/商用 |

**硬规则**：

- 论文默认最多到 TRL 4；出现明确中试/放大证据才可到 5；没有装车/现场/量产证据不得标 7—9。
- 每个 TRL 必须带 `trl_evidence` 原文摘录；无证据则 `trl=null`、`review_status=needs_review`。
- 需求侧 `required_trl` 由企业填报；模拟需求按行业常识设定，并标 `is_simulated=true`。

## 5. `cooperation_mode`（合作模式）

| code | 中文 | 说明 |
| --- | --- | --- |
| `transfer` | 技术转让 | 所有权转移，一次性/分期对价 |
| `license` | 技术许可 | 保留所有权，授权使用 |
| `joint_rd` | 联合研发 | 双方共同投入、共享成果 |
| `joint_lab` | 共建实验室 | 长期平台型合作 |
| `tech_service` | 技术服务/咨询 | 委托开发、检测、咨询 |

成果侧的 `cooperation_mode` 只作为“潜在模式”推断，`confidence ≤0.5`，不用于硬过滤；需求侧按企业填报，用于兼容性打分和风险提示。

## 6. 辅助字段

### 6.1 `ip_status`

| code | 中文 | 说明 |
| --- | --- | --- |
| `granted` | 已授权 | 有授权专利号/证书 |
| `pending` | 申请中 | 已受理未授权 |
| `published` | 已公开 | 公开但未授权 |
| `unknown` | 未知/不适用 | 论文、或无法确认 |

论文默认 `unknown`；专利按法律状态；不得把论文推断为“已授权”。

### 6.2 `target_region`

`yangtze_delta`（长三角）、`pearl_river_delta`（珠三角）、`beijing_tianjin_hebei`（京津冀）、`chengdu_chongqing`（成渝）、`other`（其他）、`any`（不限）。

### 6.3 `target_industry`

`battery_manufacturing`（电池制造）、`material_manufacturing`（材料制造）、`ev_oem`（整车）、`ess_integrator`（储能系统）、`recycling`（回收）、`other`（其他）。

## 7. 同义词/术语表（用于查询与归一化）

| 标准词 | 中文变体 | 英文变体 |
| --- | --- | --- |
| 固态电解质 | 固态电解质、固体电解质、全固态电解质 | solid electrolyte, solid-state electrolyte, SSE |
| 硫化物电解质 | 硫化物固态电解质、硫银锗矿 | sulfide electrolyte, argyrodite, Li6PS5Cl, LPSCl |
| 氧化物电解质 | 氧化物固态电解质、石榴石型 | oxide electrolyte, LLZO, LATP, LAGP, garnet, perovskite |
| 聚合物电解质 | 聚合物固态电解质 | polymer electrolyte, PEO, PVDF, PMMA |
| 卤化物电解质 | 卤化物固态电解质 | halide electrolyte, Li3YCl6, Li3InCl6 |
| 硅碳负极 | 硅碳、硅基负极、硅氧负极 | silicon-carbon, Si-C, Si/C, silicon anode, SiOx |
| 硬碳 | 硬碳负极 | hard carbon, HC |
| 高镍正极 | 高镍三元、NCM811、NCM9½½ | high-nickel, Ni-rich, NCM811, NCA |
| 磷酸铁锂 | 铁锂、LFP | LFP, LiFePO4, lithium iron phosphate |
| 钠离子电池 | 钠电、钠离子 | sodium-ion, Na-ion, SIB |
| 液流电池 | 全钒液流、氧化还原液流 | flow battery, redox flow, VRFB |
| 超级电容器 | 超容、电化学电容器 | supercapacitor, ultracapacitor, EDLC |
| 回收 | 再生、资源化、梯次利用 | recycling, regeneration, recovery, second-life |
| 隔膜 | 电池隔膜、涂覆隔膜 | separator, membrane, ceramic-coated separator |
| 热失控 | 热失控蔓延、热扩散 | thermal runaway, thermal propagation |
| 技术成熟度 | TRL | technology readiness level, TRL |

## 8. LLM 映射规则

### 8.1 输入

- 标题、摘要、期刊/年份、源关键词、源主题。
- 本文件的枚举定义与同义词表。
- 输出 JSON schema。

### 8.2 输出

```json
{
  "tech_fields": [
    {"code": "electrolyte", "is_primary": true, "confidence": 0.93, "evidence": "sulfide solid electrolyte"}
  ],
  "application_scenarios": [
    {"code": "ev_power", "confidence": 0.72, "evidence": "electric vehicles"}
  ],
  "trl": 4,
  "trl_confidence": 0.66,
  "trl_evidence": "coin cell ...",
  "material_system": "硫化物固态电解质",
  "key_metrics": [
    {"name": "ionic conductivity", "value": "10", "unit": "mS/cm", "evidence": "..."}
  ],
  "process": ["ball milling", "cold sintering"],
  "cooperation_modes": [
    {"code": "joint_rd", "confidence": 0.4, "evidence": "potential"}
  ],
  "ip_status": "unknown",
  "unknowns": ["target_region"]
}
```

### 8.3 硬约束

1. 只能输出本文件中的 code；非法 code 直接拒绝并重试。
2. 每个 label 必须有 `evidence`；无证据时 `confidence ≤0.4`、`review_status=needs_review`。
3. `tech_fields` 必须恰好一个 `is_primary=true`；最多 2 个。
4. `trl` 必须给 `trl_evidence`；无证据输出 `null`。
5. 不确定的字段写 `unknown`，不得编造性能指标、IP 状态、合作模式。
6. 成果侧 `cooperation_mode` 只是潜在模式，`confidence ≤0.5`，不参与硬过滤。

## 9. 标注流程与一致性

1. **抽样**：按 8 个 `tech_field` 分层，抽 20 条成果（每类 2—3 条）；覆盖有歧义、缺摘要、跨领域、TRL 边界样本。
2. **双人独立标注**：DE + AI 各标一遍，填写 `label_samples_v0.1.jsonl`（待生成）。
3. **一致性**：每个维度算 Cohen's kappa；目标 ≥0.6（moderate）。低于 0.6 先修定义，不进入全量。
4. **裁决会**：30 分钟，逐条讨论分歧；记录裁决理由；确认冻结 `taxonomy_v0.1`。
5. **LLM 校准**：用同一批 20 条跑抽取，逐字段比对；再抽 10 条验证；标签准确率目标 ≥90%。
6. **变更**：任何枚举调整升级 `taxonomy_version`；旧数据保留原版本，重跑后再切换。

## 10. 示例

### 10.1 成果

```json
{
  "achievement_id": "ach_openalex_W2587767928",
  "title_original": "Lithium battery chemistries enabled by solid-state electrolytes",
  "tech_fields": [
    {"code": "electrolyte", "is_primary": true, "confidence": 0.95, "evidence": "solid-state electrolytes"}
  ],
  "application_scenarios": [
    {"code": "ev_power", "confidence": 0.7, "evidence": "lithium battery chemistries"}
  ],
  "trl": 4,
  "trl_confidence": 0.6,
  "trl_evidence": "review of cell-level demonstrations",
  "material_system": "固态电解质（多体系综述）",
  "ip_status": "unknown",
  "cooperation_modes": [
    {"code": "joint_rd", "confidence": 0.4, "evidence": "potential"}
  ]
}
```

### 10.2 需求

```json
{
  "demand_id": "dem_005",
  "title": "硫化物固态电解质中试放大",
  "tech_fields": ["electrolyte"],
  "application_scenarios": ["ev_power"],
  "required_trl": 5,
  "cooperation_modes": ["joint_rd", "joint_lab"],
  "technical_metrics": [
    {"name": "室温离子电导率", "value": ">=10", "unit": "mS/cm"},
    {"name": "空气稳定性", "value": "暴露 24h 后电导率保持 >=80%", "unit": "%"}
  ],
  "is_simulated": true
}
```

## 11. 版本记录

| 版本 | 日期 | 变更 | 负责人 |
| --- | --- | --- | --- |
| v0.1 | 2026-11-17 | 初版：4 维 + 3 辅助字段；8 个技术领域；8 个应用场景；5 种合作模式；TRL 口径 | 黄欣悦、陈镇灏 |
