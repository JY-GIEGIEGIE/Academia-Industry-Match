# Embedding 的 text_type 口径（2026-11-19）

> 适用：`scripts/data/embed.py`、`embeddings_v0.1.jsonl`、`embedding` 表
> 依据：`data/spec/data_contract_v0.1.md` 第 4.3、4.6、6.4 节；`scripts/common/llm_client.py`
> 作者：张小桐（BE2）｜待陈镇灏（AI）确认第 7 节

## 1. 一句话

`text_type` 有两个层次，**不要混用**：调 API 时是 `document`/`query`，落库时是 `capability_profile`/`need_profile`（契约 6.4 只要求向量化这两类文本）。

## 2. 两层含义

| 层次 | 出现位置 | 合法取值 | 作用 |
| --- | --- | --- | --- |
| API 参数 | `embed_texts(texts, text_type=...)` | `document` / `query` | 区分“入库文本”和“检索 query”；参与缓存键，影响 Qwen 的向量化模式 |
| 落库字段 | `embedding.text_type`（契约 4.6） | `title` / `abstract` / `capability_profile` / `need_profile` | 说明这条向量对应哪一种派生文本 |

组长的“入库文本 `text_type=document`、检索 query `text_type=query`”说的是**第一层**。如果把 `document` 直接写进 `embeddings_v0.1.jsonl` 的 `text_type` 字段，导入校验会直接报错：

```
embedding[1] emb_xxx: text_type='document' invalid
```

## 3. 本次冲刺的向量化对象

契约第 6.4 节写的是：**向量化 `capability_profile` / `need_profile`，原始摘要只做证据**。所以薄切片和全量都按这个执行：

| 数据 | 向量化文本 | `object_type` | 落库 `text_type` | API `text_type` |
| --- | --- | --- | --- | --- |
| 成果 | 能力画像 `capability_profile` | `achievement` | `capability_profile` | `document` |
| 需求 | 需求画像 `need_profile` | `demand` | `need_profile` | `document` |
| 检索 query | 查询文本（评测用） | `eval_query` | 见第 4 节 | `query` |

`title` / `abstract` 在枚举里合法，但本冲刺**不作为覆盖率要求**；如果为了消融实验额外向量化标题，可以入库，`text_type=title`，但不要和画像向量混在同一次覆盖率统计里。

## 4. 待确认：query 向量要不要入库

`embedding.text_type` 的枚举里没有 `query`，但评测需要 query 向量。三个选项：

| 选项 | 做法 | 代价 |
| --- | --- | --- |
| **A（建议）** | query 向量**不入 `embedding` 表**，评测时用 `embed_texts(text_type="query")` 现算 | 有 text_hash 缓存，不会重复计费；契约不用改 |
| B | 入库，`text_type` 填 `need_profile` | 语义不准，事后无法区分 query 和需求画像 |
| C | 给契约枚举加 `query` | 要 DE/AI/BE2 三人同意并改 `data_contract_v0.1.md` |

建议选 **A**：评测脚本 `evaluate.py` 自己算 query 向量并缓存，入库只存成果和需求的画像向量。这样“向量覆盖率 100%”指的是成果 + 需求，口径清楚，也不用动契约。

## 5. `embeddings_v0.1.jsonl` 示例

成果向量：

```json
{"embedding_id":"emb_ach_0001_cap","object_type":"achievement","object_id":"ach_openalex_W4210818813","text_type":"capability_profile","model":"qwen3.7-text-embedding-flash","dim":1024,"text_hash":"<归一化文本的 sha256>","vector":[0.001,0.002,...],"dataset_version":"v0.1-thin"}
```

需求向量：

```json
{"embedding_id":"emb_dem_0001_need","object_type":"demand","object_id":"dem_0001","text_type":"need_profile","model":"qwen3.7-text-embedding-flash","dim":1024,"text_hash":"<归一化文本的 sha256>","vector":[0.001,0.002,...],"dataset_version":"v0.1-thin"}
```

字段要求：

- `text_hash` 与生成向量的**归一化文本**一致（`llm_client.text_hash()`）；同一 `(object_type, object_id, text_type, model, text_hash)` 只能有一条。
- `dim` 固定 1024；`vector` 是 1024 个 float 的数组。
- 换模型、换文本、换预处理都必须重算并换 `text_hash`，不得混维。
- 模型统一 `qwen3.7-text-embedding-flash`，`embedding_model_version` 由 AI/DE 定一个固定串（如 `qwen3.7-text-embedding-flash-1024-v1`），导入时通过 `--embedding-model-version` 传入。

## 6. 导入侧会做的校验

`python scripts/data/load_db.py --check` 会拒绝以下情况，提前自查可以省一轮返工：

| 校验 | 报错示例 |
| --- | --- |
| `text_type` 不在枚举内 | `embedding[1] emb_x: text_type='document' invalid` |
| `object_type` 不在枚举内 | `embedding[1] emb_x: object_type='paper' invalid` |
| `object_id` 找不到对应成果/需求 | `unknown achievement object_id ach_xxx` |
| `dim` 不是 1024 | `dim=768, expected 1024` |
| 向量长度不是 1024 | `vector must be a list of 1024 numbers` |
| 向量含非数字元素 | `vector contains non-numeric values` |
| 唯一键重复 | `duplicate embedding key (...)` |

## 7. 需要回复的

### 7.1 query 向量选 A、B 还是 C（见第 4 节）

> **建议回复**：选 A。query 向量不入 `embedding` 表，评测时用 `embed_texts(text_type="query")` 现算，缓存到 `data/interim/embedding_cache.jsonl`。理由是契约 6.4 的“覆盖率 100%”针对成果和需求，query 不是入库对象；选 B 语义不准，选 C 要改契约。`evaluate.py` 算完 query 向量后走 text_hash 缓存，重复评测不重复计费，20 条 query 首次成本可忽略。

### 7.2 `embedding_model_version` 用什么固定串

> **建议回复**：统一 `qwen3.7-text-embedding-flash-1024-v1`。规则是 `<模型>-<维度>-<预处理版本>`，契约 4.6 的示例 `bge-m3-1024-v1` 就是这个格式。这个值会写进 `dataset_manifest.embedding_model`，也是 `match_score` 唯一键的一部分，**一旦定下不要中途改**；如果截断规则、是否加标题前缀等预处理变了，升 `v2` 并重算，不要覆盖 v1。

### 7.3 `capability_profile` 的语言

> **建议回复**：本冲刺只做中文单条 `capability_profile`。英文成果的画像由 LLM 从英文原文生成中文，因为需求侧 `need_profile` 必然是中文，跨语言匹配靠 Qwen 的多语言能力，不需要双语各一条、翻倍向量数和调用成本。若后续要做中英双语，注意当前导入按 `(object_type, object_id, text_type, model)` 替换：同一成果的 zh 和 en 画像向量会互相覆盖，最终只保留最后导入的一条。要做双语必须先改存储口径（例如给 `text_type` 增加语言维度，允许同对象多版本），由 BE2 与 AI 一起定，不要在数据里自行假设。

### 7.4 提议的最终口径（确认这四条即可开工）

| 项 | 取值 |
| --- | --- |
| 向量化文本 | 成果 `capability_profile`、需求 `need_profile`；摘要不入向量 |
| API `text_type` | 入库文本 `document`；检索 query `query` |
| 落库 `embedding.text_type` | `capability_profile` / `need_profile` |
| query 向量 | 不入库，评测时现算并缓存 |
| 模型与版本 | `qwen3.7-text-embedding-flash`，1024 维，`qwen3.7-text-embedding-flash-1024-v1` |
