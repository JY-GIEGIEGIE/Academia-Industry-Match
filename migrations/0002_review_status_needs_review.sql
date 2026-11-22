-- migrations/0002_review_status_needs_review.sql
-- review_status on tag/extraction tables now allows needs_review.
-- Source: 2026-11-21 team sync; data_contract §4.4/4.5/6.3.
-- 0001 is already applied in existing databases, so change it here.

BEGIN;

-- Drop whatever auto-named CHECK references review_status, then add a
-- clearly named one. This keeps the migration idempotent: apply_migrations
-- re-runs every file on each import.
DO $$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT conrelid::regclass AS table_name, conname
        FROM pg_constraint
        WHERE conrelid IN (
                'achievement_tag'::regclass,
                'achievement_extraction'::regclass,
                'demand_tag'::regclass
              )
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%review_status%'
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', target.table_name, target.conname);
    END LOOP;
END $$;

ALTER TABLE achievement_tag
    ADD CONSTRAINT achievement_tag_review_status_check
    CHECK (review_status IN ('pending', 'approved', 'rejected', 'needs_review'));

ALTER TABLE achievement_extraction
    ADD CONSTRAINT achievement_extraction_review_status_check
    CHECK (review_status IN ('pending', 'approved', 'rejected', 'needs_review'));

-- §4.9 says demand_tag has the same fields as achievement_tag; keep one enum.
ALTER TABLE demand_tag
    ADD CONSTRAINT demand_tag_review_status_check
    CHECK (review_status IN ('pending', 'approved', 'rejected', 'needs_review'));

COMMIT;
