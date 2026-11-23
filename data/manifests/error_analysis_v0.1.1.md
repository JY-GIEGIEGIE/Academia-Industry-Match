# v0.1 基线错误分析（B2-any 补充口径）

> 对象：S-08 补充报告中的 B2（任一 `tech_field` 命中 + 向量）。
> 5 假阳 + 5 假阴为自动选取的检查样本，理由为归因建议，不替代人工逐条复核。

| 类型 | query | 成果 | grade | rank | 根因/建议 |
| --- | --- | --- | ---: | ---: | --- |
| FP | `q01` | `ach_openalex_W3003014070` Progress and Perspective of Ceramic/Polymer Composite Solid Electrolytes for Lithium Batteries | 0 | 5 | 同领域候选被标签/向量排进 Top10，人工判 0；B2 只能保证大类，需 B3 核验材料体系、场景或证据。 |
| FP | `q01` | `ach_openalex_W4293238043` Ionic conductivity and ion transport mechanisms of solid‐state lithium‐ion battery electrolytes: A review | 0 | 9 | 同领域候选被标签/向量排进 Top10，人工判 0；B2 只能保证大类，需 B3 核验材料体系、场景或证据。 |
| FP | `q01` | `ach_openalex_W2999393849` Fast Li + Conduction Mechanism and Interfacial Chemistry of a NASICON/Polymer Composite Electrolyte | 0 | 10 | 同领域候选被标签/向量排进 Top10，人工判 0；B2 只能保证大类，需 B3 核验材料体系、场景或证据。 |
| FP | `q02` | `ach_openalex_W4390726237` Regulation of Coordination Chemistry for Ultrastable Layered Oxide Cathode Materials of Sodium‐Ion Batteries | 0 | 6 | 同领域候选被标签/向量排进 Top10，人工判 0；B2 只能保证大类，需 B3 核验材料体系、场景或证据。 |
| FP | `q02` | `ach_openalex_W4402675210` Lithium-ion battery fundamentals and exploration of cathode materials: A review | 0 | 7 | 同领域候选被标签/向量排进 Top10，人工判 0；B2 只能保证大类，需 B3 核验材料体系、场景或证据。 |
| FN | `q04` | `ach_openalex_W4414346831` Clay‐Mineral‐Coated Separators for Lithium‐Ion Batteries: Exploring the Relationships between Clay Mineral Morphology and Separator Performance | 1 | 12 | 人工判为相关但未进 Top10；可能是画像压缩、系统级/组件级粒度差异或 query 表达差异。 |
| FN | `q07` | `ach_openalex_W4319778200` A Review on Vanadium Redox Flow Battery Storage Systems for Large-Scale Power Systems Application | 1 | 12 | 人工判为相关但未进 Top10；可能是画像压缩、系统级/组件级粒度差异或 query 表达差异。 |
| FN | `q09` | `ach_openalex_W4386945441` Kinetic Limits of Graphite Anode for Fast-Charging Lithium-Ion Batteries | 1 | 11 | 人工判为相关但未进 Top10；可能是画像压缩、系统级/组件级粒度差异或 query 表达差异。 |
| FN | `q09` | `ach_openalex_W4292309746` A review of carbon materials for supercapacitors | 1 |  | 人工判为相关但未进 Top10；可能是画像压缩、系统级/组件级粒度差异或 query 表达差异。 |
| FN | `q10` | `ach_openalex_W4293238043` Ionic conductivity and ion transport mechanisms of solid‐state lithium‐ion battery electrolytes: A review | 1 | 13 | 人工判为相关但未进 Top10；可能是画像压缩、系统级/组件级粒度差异或 query 表达差异。 |

- 这不是 S-04 正式 B2-primary 的错误分析；若 PM 将 B2-any 定为正式口径，应重新生成正式错误分析并保留本文件为敏感性分析。