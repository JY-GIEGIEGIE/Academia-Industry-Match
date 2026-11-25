-- migrations/0004_users_publish_intent.sql
-- 第二轮 S-12：演示账号、发布者归属与意向表。
-- 字段口径见《第二轮冲刺目标与方案_2026-11-25》§4.2 和任务分配 S-12。
-- 该文件会在每次 --migrate 时重跑，必须保持幂等。

BEGIN;

CREATE TABLE IF NOT EXISTS app_user (
    user_id          TEXT PRIMARY KEY,
    username         TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('researcher', 'enterprise')),
    display_name     TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 现有 v0.1.2 数据没有发布者，列保持 NULL；发布动作由 API 写入。
ALTER TABLE achievement
    ADD COLUMN IF NOT EXISTS publisher_user_id TEXT
        REFERENCES app_user(user_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

ALTER TABLE demand
    ADD COLUMN IF NOT EXISTS publisher_user_id TEXT
        REFERENCES app_user(user_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_achievement_publisher
    ON achievement (publisher_user_id);
CREATE INDEX IF NOT EXISTS ix_demand_publisher
    ON demand (publisher_user_id);

-- 一个 (achievement, demand) pair 只保留一条意向记录，发起方记录在
-- initiator_user_id；另一方确认后 status=confirmed 且 contact_revealed=true。
-- 唯一约束只锁 pair，不把发起方计入，避免双方同时点击产生两条意向。
CREATE TABLE IF NOT EXISTS intent (
    intent_id          TEXT PRIMARY KEY,
    achievement_id     TEXT NOT NULL REFERENCES achievement(achievement_id) ON DELETE CASCADE,
    demand_id          TEXT NOT NULL REFERENCES demand(demand_id) ON DELETE CASCADE,
    initiator_user_id  TEXT NOT NULL REFERENCES app_user(user_id) ON DELETE RESTRICT,
    status             TEXT NOT NULL DEFAULT 'expressed'
        CHECK (status IN ('expressed', 'confirmed', 'declined', 'closed')),
    contact_revealed   BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_intent_pair UNIQUE (achievement_id, demand_id)
);

CREATE INDEX IF NOT EXISTS ix_intent_initiator_status
    ON intent (initiator_user_id, status);
CREATE INDEX IF NOT EXISTS ix_intent_demand
    ON intent (demand_id, status);
CREATE INDEX IF NOT EXISTS ix_intent_status
    ON intent (status);

COMMIT;
