# 基线错误分析 v0.1（B2 any-tag）

> 分析对象：`data/manifests/baseline_v0.1.md` 的 B2（任一 tech_field 命中 + 向量）；query 向量使用 `data/interim/eval_query_vectors_v0.1.jsonl` 冻结版本。5 假阳 + 5 假阴，证据以标题/摘要片段为主，完整原文在私有数据中。

| 类型 | query | 成果 | 人工 grade | B2 rank/score | 根因 | 处理建议 |
| --- | --- | --- | ---: | --- | --- | --- |
| FP | `q14` | `ach_openalex_W3000982183` Lithium‐Ion Battery Separators for Ionic‐Liquid Electrolytes: A Review | 0 | 1 / 0.633 | review_vs_experimental | 在 B3 增加陶瓷涂层/热收缩证据检查；B2 可把 review 作为弱证据。 |
| FP | `q03` | `ach_openalex_W4395466669` Consummating ion desolvation in hard carbon anodes for reversible sodium storage | 0 | 2 / 0.59 | material_system_mismatch | 把材料体系/场景作为硬约束或重排特征；标注为同领域不同路线 hard negative。 |
| FP | `q01` | `ach_openalex_W3003014070` Progress and Perspective of Ceramic/Polymer Composite Solid Electrolytes for Lithium Batteries | 0 | 5 / 0.64 | route_mismatch | 要求 sulfide/argyrodite 证据；B3 使用摘要片段核验。 |
| FP | `q02` | `ach_openalex_W4390726237` Regulation of Coordination Chemistry for Ultrastable Layered Oxide Cathode Materials of Sodium‐Ion Batteries | 0 | 6 / 0.563 | chemistry_mismatch | 增加 Ni-rich/NCM/单晶关键词和材料体系约束。 |
| FP | `q04` | `ach_openalex_W3009576992` Preparation and Characterization of Biopolymer Electrolyte Membranes Based on LiClO4-Complexed Methyl Cellulose as Lithium-ion Battery Separator | 0 | 5 / 0.635 | function_mismatch | 按功能角色过滤；将电解质膜从 separator 候选降权。 |
| FN | `q07` | `ach_openalex_W4319778200` A Review on Vanadium Redox Flow Battery Storage Systems for Large-Scale Power Systems Application | 1 | 12 / 0.441 | query_profile_gap | 保留 system/review 为部分相关；B3 使用系统级摘要。 |
| FN | `q10` | `ach_openalex_W4392013241` PDOL-Based Solid Electrolyte Toward Practical Application: Opportunities and Challenges | 1 | 14 / 0.446 | material_route_shift | 在 B3 允许路线迁移的部分相关；不要硬过滤。 |
| FN | `q12` | `ach_openalex_W4212972170` Cobalt‐Free Cathode Materials: Families and their Prospects | 1 | 11 / 0.422 | chemistry_mismatch | 增加 chemistry/单晶证据；保留为 grade 1 候选。 |
| FN | `q17` | `ach_openalex_W4390871224` Experimental Validation of Side Reaction on Capacity Fade of Vanadium Redox Flow Battery | 1 | 11 / 0.492 | system_vs_component | 在 B3 交叉摘要；区分组件级和系统级证据。 |
| FN | `q18` | `ach_openalex_W4221038135` Conductive Metal–Organic Frameworks for Supercapacitors | 1 | 12 / 0.46 | profile_compression | 补充关键指标/摘要证据；B3 精排。 |

## 说明

- 假阳主要来自“同领域/同词面但材料体系、功能角色或证据不足”；B2 的字段硬过滤只能保证大类。
- 假阴主要来自 profile/摘要压缩、系统级综述与组件级 query 的粒度差异；不是 B2 过滤缺失。
- 本分析使用最终冻结 query 向量；如果重跑 query 向量，必须重新选择 5+5，不能沿用旧明细。
- 完整逐条字段见 `error_analysis_v0.1.csv`。
