# 标注一致性报告（加权 Cohen's kappa）

- 生成时间：2026-11-22T12:26:25.896829+00:00
- 类型：queries；权重：linear
- primary：`data\eval\retrieval_queries_v0.1.csv`
- secondary：`data\interim\double_label\v0.1\query_double_blank_filled.csv`

## 主结果

- 可比较条目：80（共同 key 80；仅 primary 320；仅 secondary 0；跳过 0）
- 同分率：0.76875
- 期望一致率：0.5675
- 加权 kappa：**0.465318**（中等）
- 分数分布：primary {0: 52, 1: 21, 2: 7}；secondary {0: 32, 1: 24, 2: 24}
- 仅 primary 示例：[['q01', 'ach_openalex_W2999393849'], ['q01', 'ach_openalex_W3000982183'], ['q01', 'ach_openalex_W3003014070'], ['q01', 'ach_openalex_W3003387392'], ['q01', 'ach_openalex_W3082954565']]

## 混淆矩阵（行=primary，列=secondary）

| primary \ secondary | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 32 | 19 | 1 |
| 1 | 0 | 5 | 16 |
| 2 | 0 | 0 | 7 |

## 口径

- 加权 Cohen's kappa：线性权重 1-|i-j|/2；二次权重 1-((i-j)/2)^2。
- query 未标注候选默认按 0 分处理（可用 --no-blank-as-zero 关闭）。
- kappa ≥0.6 为验收目标；低于 0.6 先检查 0/1/2 边界定义，再重标分歧项。
