# 标注一致性报告（加权 Cohen's kappa）

- 生成时间：2026-11-22T10:13:24.214535+00:00
- 类型：pairs；权重：linear
- primary：`data\interim\eval_prelabel\v0.1\pair_review.csv`
- secondary：`data\eval\pair_labels_v0.1.csv`

## 主结果

- 可比较条目：50（共同 key 50；仅 primary 0；仅 secondary 0；跳过 0）
- 同分率：0.94
- 期望一致率：0.8072
- 加权 kappa：**0.688797**（较强）
- 分数分布：primary {0: 14, 1: 36}；secondary {0: 12, 1: 38}

## 混淆矩阵（行=primary，列=secondary）

| primary \ secondary | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 10 | 4 | 0 |
| 1 | 2 | 34 | 0 |
| 2 | 0 | 0 | 0 |

## LLM 预标 vs 人工（参考）

- 可比较条目：50
- 同分率：0.94
- 加权 kappa：**0.688797**（较强）

| LLM \ 人工 | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 10 | 4 | 0 |
| 1 | 2 | 34 | 0 |
| 2 | 0 | 0 | 0 |

注意：LLM-人工一致性只用于评估预标质量，不能替代人工-人工 kappa 的验收。

## 口径

- 加权 Cohen's kappa：线性权重 1-|i-j|/2；二次权重 1-((i-j)/2)^2。
- query 未标注候选默认按 0 分处理（可用 --no-blank-as-zero 关闭）。
- kappa ≥0.6 为验收目标；低于 0.6 先检查 0/1/2 边界定义，再重标分歧项。
