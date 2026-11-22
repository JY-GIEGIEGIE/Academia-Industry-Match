# S-03 全量（300 条）人工抽检报告（修订版）

> 修订说明：本文件替换 S-03/S-04 交接包中的旧 `extract_sample_report_v0.1.md`。旧报告写“`needs_review` 为 0、画像全部 150—250 字、TRL 全部 2—4”，但同包的 `achievements_labeled_v0.1.jsonl`、`capability_profiles_v0.1.jsonl` 和 `extract_v0.1-20261122.json` 明确记录了 79 条 `needs_review`、74 条画像超过 250 字和 58 条 TRL=null。旧报告是未与最终 JSONL 对齐的旧模板/人工汇总，不能作为质量证据；本修订以最终文件为准重新计算。

## 数据源

- `data/processed/achievements_labeled_v0.1.jsonl`：300 条，SHA-256 `fa1eb22990ec0157e2c8eb98628304160402df671f3d334999af48f700fbf73c`
- `data/processed/capability_profiles_v0.1.jsonl`：300 条，SHA-256 `b87d25fb6ee0cce830ae4a0a337324d1efe78cdbf8eabc3253508963f4a5629d`
- `data/manifests/extract_v0.1-20261122.json`：`ok=221`、`needs_review=79`；原因分类 `profile=74`、`key_metrics=4`、`trl=2`、`retry_exhausted=1`、`tech_field=1`（分类可重叠）

## 本次抽检

- 抽检样本：沿用原抽检表的 30 条（占全量 10%），ID 和顺序不变；详见 `extract_sample_checks_v0.1.csv`
- 人工核对：原 CSV 的 `人工核对(填Y/N)` 保留为 **30/30 Y**；这只表示原抽检人对内容的判定，不等于结构门禁全部通过
- 结构状态：**pending 22 条，needs_review 8 条**
- 画像长度：**150—250 字 22 条，超过 250 字 8 条**（最长 280 字）
- TRL：**2—4 级 25 条，null 5 条**
- `needs_review` 的 8 条全部由画像超界触发：`ach_openalex_W4407275632、ach_openalex_W4406100977、ach_openalex_W3012674055、ach_openalex_W4416407888、ach_openalex_W4312230144、ach_openalex_W7204767311、ach_openalex_W7213442247、ach_openalex_W7215028800`
- TRL=null 的 5 条仍为 `pending`，没有触发 `needs_review`：`ach_openalex_W4414346831、ach_openalex_W7146945464、ach_openalex_W4408296453、ach_openalex_W7225615065、ach_openalex_W4405370600`；这是 S-03 当前的口径缺口，留给 S-08 统一处置

## 结论

1. 旧报告中的 `needs_review=0`、画像全部 150—250 字、TRL 全部 2—4、`key_metrics` 全部 2—5 均与最终数据不符，已撤回。
2. 30 条样本的内容级人工核对为 Y，但结构门禁仍有 8 条画像超界和 5 条 TRL=null；交付时必须保留这些状态，不能表述为“全部通过”。
3. 全量 300 条中仍有 79 条 `needs_review`、74 条画像超过 250 字、58 条 TRL=null；S-04 基线可以使用完整数据，但这些记录需由 S-08 做最终处置并在质量报告中说明。
4. 若后续修改画像文本或 TRL 状态，必须同步重算 embeddings 和基线，并更新哈希。
