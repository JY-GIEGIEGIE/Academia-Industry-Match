# 标注一致性报告（加权 Cohen's kappa）

- 生成时间：2026-11-22T11:10:13.258972+00:00
- 类型：queries；权重：linear
- primary：`data\eval\retrieval_queries_v0.1.csv`
- secondary：`data\interim\eval_prelabel\v0.1\query_candidates_review.csv`

## 主结果

- 可比较条目：400（共同 key 400；仅 primary 0；仅 secondary 0；跳过 0）
- 同分率：0.86625
- 期望一致率：0.672325
- 加权 kappa：**0.591821**（中等）
- 分数分布：primary {0: 276, 1: 109, 2: 15}；secondary {0: 222, 1: 118, 2: 60}

## 混淆矩阵（行=primary，列=secondary）

| primary \ secondary | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 218 | 55 | 3 |
| 1 | 4 | 63 | 42 |
| 2 | 0 | 0 | 15 |

## LLM 预标 vs 人工（参考）

- 可比较条目：400
- 同分率：0.86625
- 加权 kappa：**0.591821**（中等）

| LLM \ 人工 | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 218 | 4 | 0 |
| 1 | 55 | 63 | 0 |
| 2 | 3 | 42 | 15 |

注意：LLM-人工一致性只用于评估预标质量，不能替代人工-人工 kappa 的验收。

## 口径

- 加权 Cohen's kappa：线性权重 1-|i-j|/2；二次权重 1-((i-j)/2)^2。
- query 未标注候选默认按 0 分处理（可用 --no-blank-as-zero 关闭）。
- kappa ≥0.6 为验收目标；低于 0.6 先检查 0/1/2 边界定义，再重标分歧项。
