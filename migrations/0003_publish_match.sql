-- migrations/0003_publish_match.sql
-- 第二轮 S-12：发布触发的匹配结果在 B2 阶段可以没有 risk/evidence。
-- 同时为“按成果/需求取 Top-K”补复合索引。
-- 该文件会在每次 --migrate 时重跑，必须保持幂等。

BEGIN;

-- B2 只产出分数与规则理由，risk/evidence 由 P1 LLM 精排补齐。
ALTER TABLE match_score ALTER COLUMN risk DROP NOT NULL;
ALTER TABLE match_score ALTER COLUMN evidence DROP NOT NULL;

-- 现有单列索引 + total_score 索引无法同时服务过滤和排序，补两个复合索引。
CREATE INDEX IF NOT EXISTS ix_match_score_demand_top
    ON match_score (demand_id, total_score DESC);
CREATE INDEX IF NOT EXISTS ix_match_score_achievement_top
    ON match_score (achievement_id, total_score DESC);

COMMIT;
