# 评测标注最终报告（v0.1）

- 冻结时间：2026-11-22T12:33:58.422819+00:00
- query：20 条；pair：50 对
- query 最终分数：{1: 129, 2: 15}；未标候选按 0（256 个）
- pair 最终分数：{0: 12, 1: 38}
- 双标：query 线性 0.4653 / 二次 0.6321；pair 线性 0.4828 / 二次 0.5714
- 裁决：20 条 query 0→1；3 条 pair 分歧按 P1/P2/P3 裁决；详见 `data/manifests/eval_adjudication_v0.1.md`

## 文件

- `data/eval/retrieval_queries_v0.1.csv` sha256=`e895290744b33b2233779a2477af28d1fc5b1084ec459f00adbb5862ccddb62b`
- `data/eval/retrieval_queries_v0.1.jsonl` sha256=`3de11bf3264a3549a56fa801628aa9cf920c4c09408d3a6542d2a62a1d0ab897`
- `data/eval/pair_labels_v0.1.csv` sha256=`887a67953a1cddd34f4b2c0d276eac1a360762ed34bebc432e889b1192913bca`
- `data/eval/pair_labels_v0.1.jsonl` sha256=`aec07f2d7d15312984764710af084eda645f389f35f99e272f207257b68fb97e`

## 结论

- 正式评测集使用人工首标 + 双标裁决后的标签；LLM 预标仅作对照，不进入正式文件。
- query 的人工 2 分集中在英文/宽口径 query；中文硬指标 query 严格按“硬约束是否被直接覆盖”给分。
- pair 零 2 分是候选集性质；不强行改 2。
