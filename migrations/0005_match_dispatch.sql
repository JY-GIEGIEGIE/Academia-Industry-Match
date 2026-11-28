-- S-11 / S-12: 持久化匹配任务投递记录

CREATE TABLE IF NOT EXISTS match_dispatch (
    run_id TEXT PRIMARY KEY,

    object_type TEXT NOT NULL
        CHECK (object_type IN ('achievement', 'demand')),

    object_id TEXT NOT NULL,
    publisher_user_id TEXT NOT NULL
        REFERENCES app_user(user_id),

    dispatch_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            dispatch_status IN (
                'pending',
                'submitting',
                'submitted',
                'retryable'
            )
        ),

    attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),

    last_error TEXT,
    claimed_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_match_dispatch_status
    ON match_dispatch (dispatch_status, updated_at);
