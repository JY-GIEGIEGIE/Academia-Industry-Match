# Load report v0.1

- run_id: `load-20261119T133727106495Z`
- status: `success`
- dsn: `postgresql://aim:***@127.0.0.1:5433/academia_industry_match`
- dataset_version: `v0.1-thin`
- taxonomy_version: `v0.1`
- embedding_model_version: `null`
- started_at: `2026-11-19T13:37:27Z`
- finished_at: `2026-11-19T13:37:27Z`

## Counts

| table | rows |
| --- | ---: |
| `enterprise` | 10 |
| `achievement` | 100 |
| `demand` | 20 |
| `embedding` | 0 |
| `eval_query` | 20 |
| `eval_label` | 50 |

## Checks

| check | value | result |
| --- | ---: | --- |
| `rows_achievement` | 100 | OK |
| `rows_achievement_text` | 0 | OK |
| `rows_achievement_tag` | 0 | OK |
| `rows_achievement_extraction` | 0 | OK |
| `rows_embedding` | 0 | OK |
| `rows_enterprise` | 10 | OK |
| `rows_demand` | 20 | OK |
| `rows_demand_tag` | 0 | OK |
| `rows_match_score` | 0 | OK |
| `rows_eval_query` | 20 | OK |
| `rows_eval_label` | 50 | OK |
| `rows_raw_source_record` | 0 | OK |
| `rows_pipeline_run` | 8 | OK |
| `rows_dataset_manifest` | 8 | OK |
| `duplicate_doi` | 0 | OK |
| `orphan_embeddings` | 0 | OK |
| `vector_dim_mismatch` | 0 | OK |
| `fk_demand_enterprise` | 0 | OK |
| `fk_eval_label_achievement` | 0 | OK |
| `fk_eval_label_demand` | 0 | OK |
| `simulated_demand_false` | 0 | OK |
| `simulated_enterprise_false` | 0 | OK |
| `achievements_without_primary_tech_field` | 100 | INFO |
| `achievements_without_profile` | 100 | INFO |

## Warnings

- embeddings: file not found, skipped (C:\Users\29834\Desktop\Course\CS\软工管\repos\Academia-Industry-Match\data\processed\embeddings_v0.1-thin.jsonl)
- labeled: file not found, skipped (C:\Users\29834\Desktop\Course\CS\软工管\repos\Academia-Industry-Match\data\processed\achievements_labeled_v0.1-thin.jsonl)
- profiles: file not found, skipped (C:\Users\29834\Desktop\Course\CS\软工管\repos\Academia-Industry-Match\data\processed\capability_profiles_v0.1-thin.jsonl)
- achievements: extra build fields ignored: query_lens, query_tag, query_tags, raw_payload_path, selection_hits, selection_score
- queries: 20 rows missing dataset_version; defaulting to v0.1-thin
- pairs: 50 rows missing dataset_version; defaulting to v0.1-thin
- pairs: 50 rows have no relevance_grade (annotation pending)
- enterprises: 10 rows missing dataset_version; defaulting to v0.1-thin
- hash verification skipped by --skip-hash
