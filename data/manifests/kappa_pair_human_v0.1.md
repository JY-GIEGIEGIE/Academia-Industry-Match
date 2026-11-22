# 标注一致性报告（加权 Cohen's kappa）

- 生成时间：2026-11-22T12:26:26.079192+00:00
- 类型：pairs；权重：linear
- primary：`data\eval\pair_labels_v0.1.csv`
- secondary：`data\interim\double_label\v0.1\pair_double_blank_filled.csv`

## 主结果

- 可比较条目：10（共同 key 10；仅 primary 40；仅 secondary 0；跳过 0）
- 同分率：0.85
- 期望一致率：0.71
- 加权 kappa：**0.482759**（中等）
- 分数分布：primary {0: 6, 1: 4}；secondary {0: 6, 1: 3, 2: 1}
- ⚠ n<30，kappa 数值不稳定，需结合逐条分歧一起看。
- 仅 primary 示例：[['pair_001'], ['pair_002'], ['pair_003'], ['pair_004'], ['pair_005']]

## 混淆矩阵（行=primary，列=secondary）

| primary \ secondary | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 5 | 1 | 0 |
| 1 | 1 | 2 | 1 |
| 2 | 0 | 0 | 0 |

## 口径

- 加权 Cohen's kappa：线性权重 1-|i-j|/2；二次权重 1-((i-j)/2)^2。
- query 未标注候选默认按 0 分处理（可用 --no-blank-as-zero 关闭）。
- kappa ≥0.6 为验收目标；低于 0.6 先检查 0/1/2 边界定义，再重标分歧项。
