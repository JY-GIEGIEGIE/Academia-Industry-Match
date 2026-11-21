-- migrations/0001_init.sql
-- Target: PostgreSQL 16 + pgvector 0.8.x
-- Source of truth: data/spec/data_contract_v0.1.md
-- This is the initial schema for dataset v0.1. Later changes go in 0002_*.sql.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

SET client_encoding = 'UTF8';
SET TIME ZONE 'UTC';

-- ---------------------------------------------------------------------------
-- Raw snapshots (immutable source records)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_source_record (
    raw_id           TEXT PRIMARY KEY,
    source           TEXT NOT NULL CHECK (source IN ('openalex', 'arxiv', 'cnipa')),
    source_id        TEXT NOT NULL,
    query_tag        TEXT NOT NULL,
    lens             TEXT CHECK (lens IN ('relevance', 'recent', 'cited')),
    source_url       TEXT NOT NULL,
    retrieved_at     TIMESTAMPTZ NOT NULL,
    http_status      INTEGER NOT NULL,
    payload          JSONB NOT NULL,
    payload_hash     TEXT NOT NULL,
    license          TEXT,
    dataset_version  TEXT NOT NULL,
    raw_path         TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Pipeline runs and dataset manifests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id          TEXT PRIMARY KEY,
    stage           TEXT NOT NULL CHECK (stage IN ('fetch', 'clean', 'extract', 'embed', 'load', 'match', 'eval')),
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    input_count     INTEGER NOT NULL,
    output_count    INTEGER NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    git_commit      TEXT,
    dataset_version TEXT NOT NULL,
    log_path        TEXT
);

CREATE TABLE IF NOT EXISTS dataset_manifest (
    manifest_id             TEXT PRIMARY KEY,
    run_id                  TEXT REFERENCES pipeline_run(run_id) ON DELETE SET NULL,
    dataset_version         TEXT NOT NULL,
    taxonomy_version        TEXT NOT NULL,
    embedding_model         TEXT,
    source                  TEXT,
    counts                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    hashes                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Achievements
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS achievement (
    achievement_id    TEXT PRIMARY KEY,
    source            TEXT NOT NULL CHECK (source IN ('openalex', 'arxiv', 'cnipa')),
    source_id         TEXT NOT NULL,
    doi               TEXT,
    patent_no         TEXT,
    title_original    TEXT NOT NULL,
    abstract_original TEXT NOT NULL,
    language          TEXT NOT NULL CHECK (language IN ('en', 'zh', 'mixed', 'unknown')),
    publication_year  INTEGER NOT NULL CHECK (publication_year BETWEEN 2000 AND 2026),
    publication_date  DATE,
    type              TEXT NOT NULL CHECK (type IN ('article', 'review', 'preprint', 'patent', 'other')),
    venue             TEXT,
    authors           JSONB NOT NULL DEFAULT '[]'::jsonb,
    institutions      JSONB NOT NULL DEFAULT '[]'::jsonb,
    countries         JSONB NOT NULL DEFAULT '[]'::jsonb,
    keywords          JSONB NOT NULL DEFAULT '[]'::jsonb,
    topics            JSONB NOT NULL DEFAULT '[]'::jsonb,
    cited_by_count    INTEGER,
    source_url        TEXT NOT NULL,
    license           TEXT,
    oa_status         TEXT,
    retrieved_at      TIMESTAMPTZ NOT NULL,
    content_hash      TEXT NOT NULL,
    clean_status      TEXT NOT NULL CHECK (clean_status IN ('raw', 'cleaned', 'labeled', 'embedded', 'published')),
    review_status     TEXT NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected', 'needs_review')),
    quality_flags     JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_simulated      BOOLEAN NOT NULL DEFAULT false,
    dataset_version   TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS achievement_text (
    text_id         TEXT PRIMARY KEY,
    achievement_id  TEXT NOT NULL REFERENCES achievement(achievement_id) ON DELETE CASCADE,
    text_type       TEXT NOT NULL CHECK (text_type IN ('title_zh', 'abstract_zh', 'capability_profile_zh', 'capability_profile_en')),
    language        TEXT NOT NULL CHECK (language IN ('zh', 'en')),
    text            TEXT NOT NULL,
    method          TEXT NOT NULL CHECK (method IN ('original', 'machine', 'human', 'llm')),
    model           TEXT,
    prompt_version  TEXT,
    text_hash       TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (achievement_id, text_type, language)
);

CREATE TABLE IF NOT EXISTS achievement_tag (
    tag_id          TEXT PRIMARY KEY,
    achievement_id  TEXT NOT NULL REFERENCES achievement(achievement_id) ON DELETE CASCADE,
    dimension       TEXT NOT NULL CHECK (dimension IN ('tech_field', 'application_scenario', 'cooperation_mode')),
    code            TEXT NOT NULL,
    is_primary      BOOLEAN NOT NULL DEFAULT false,
    confidence      DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence        TEXT,
    method          TEXT NOT NULL CHECK (method IN ('llm', 'rule', 'human')),
    model           TEXT,
    prompt_version  TEXT,
    review_status   TEXT NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (achievement_id, dimension, code)
);

CREATE TABLE IF NOT EXISTS achievement_extraction (
    extraction_id       TEXT PRIMARY KEY,
    achievement_id      TEXT NOT NULL REFERENCES achievement(achievement_id) ON DELETE CASCADE,
    material_system     TEXT,
    key_metrics         JSONB NOT NULL DEFAULT '[]'::jsonb,
    process             JSONB NOT NULL DEFAULT '[]'::jsonb,
    trl                 INTEGER CHECK (trl BETWEEN 1 AND 9),
    trl_confidence      DOUBLE PRECISION CHECK (trl_confidence >= 0 AND trl_confidence <= 1),
    trl_evidence        TEXT,
    ip_status           TEXT NOT NULL CHECK (ip_status IN ('granted', 'pending', 'published', 'unknown')),
    extraction_run_id   TEXT NOT NULL REFERENCES pipeline_run(run_id) ON DELETE RESTRICT,
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    raw_output          JSONB,
    review_status       TEXT NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (achievement_id)
);

-- ---------------------------------------------------------------------------
-- Embeddings (pgvector)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding (
    embedding_id    TEXT PRIMARY KEY,
    object_type     TEXT NOT NULL CHECK (object_type IN ('achievement', 'demand', 'eval_query')),
    object_id       TEXT NOT NULL,
    text_type       TEXT NOT NULL CHECK (text_type IN ('title', 'abstract', 'capability_profile', 'need_profile')),
    model           TEXT NOT NULL,
    dim             INTEGER NOT NULL CHECK (dim = 1024),
    text_hash       TEXT NOT NULL,
    "vector"        vector(1024) NOT NULL,
    dataset_version TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (object_type, object_id, text_type, model, text_hash)
);

-- ---------------------------------------------------------------------------
-- Enterprises and demands
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enterprise (
    enterprise_id       TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    legal_name          TEXT,
    industry            TEXT NOT NULL CHECK (industry IN ('battery_manufacturing', 'material_manufacturing', 'ev_oem', 'ess_integrator', 'recycling', 'other')),
    size                TEXT NOT NULL CHECK (size IN ('large', 'medium', 'small')),
    region              TEXT NOT NULL CHECK (region IN ('yangtze_delta', 'pearl_river_delta', 'beijing_tianjin_hebei', 'chengdu_chongqing', 'other', 'any')),
    main_business       TEXT NOT NULL,
    tech_base           TEXT,
    resources           TEXT,
    prior_collaboration TEXT,
    is_simulated        BOOLEAN NOT NULL,
    source_note         TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS demand (
    demand_id            TEXT PRIMARY KEY,
    enterprise_id        TEXT NOT NULL REFERENCES enterprise(enterprise_id) ON DELETE RESTRICT,
    title                TEXT NOT NULL,
    pain_point           TEXT NOT NULL,
    expected_solution    TEXT NOT NULL,
    technical_metrics    JSONB NOT NULL DEFAULT '[]'::jsonb,
    budget_range         TEXT,
    timeline             TEXT,
    cooperation_modes    JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_trl         INTEGER NOT NULL CHECK (required_trl BETWEEN 1 AND 9),
    tech_fields          JSONB NOT NULL DEFAULT '[]'::jsonb,
    application_scenarios JSONB NOT NULL DEFAULT '[]'::jsonb,
    ip_requirement       TEXT,
    region               TEXT NOT NULL CHECK (region IN ('yangtze_delta', 'pearl_river_delta', 'beijing_tianjin_hebei', 'chengdu_chongqing', 'other', 'any')),
    status               TEXT NOT NULL CHECK (status IN ('draft', 'active', 'expired', 'closed')),
    valid_until          DATE NOT NULL,
    is_simulated         BOOLEAN NOT NULL,
    source_note          TEXT NOT NULL,
    source_urls          JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash         TEXT NOT NULL,
    dataset_version      TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS demand_tag (
    tag_id          TEXT PRIMARY KEY,
    demand_id       TEXT NOT NULL REFERENCES demand(demand_id) ON DELETE CASCADE,
    dimension       TEXT NOT NULL CHECK (dimension IN ('tech_field', 'application_scenario', 'cooperation_mode')),
    code            TEXT NOT NULL,
    is_primary      BOOLEAN NOT NULL DEFAULT false,
    confidence      DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence        TEXT,
    method          TEXT NOT NULL CHECK (method IN ('llm', 'rule', 'human')),
    model           TEXT,
    prompt_version  TEXT,
    review_status   TEXT NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (demand_id, dimension, code)
);

-- ---------------------------------------------------------------------------
-- Match results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS match_score (
    match_id                TEXT PRIMARY KEY,
    achievement_id          TEXT NOT NULL REFERENCES achievement(achievement_id) ON DELETE CASCADE,
    demand_id               TEXT NOT NULL REFERENCES demand(demand_id) ON DELETE CASCADE,
    total_score             DOUBLE PRECISION NOT NULL CHECK (total_score >= 0 AND total_score <= 100),
    tag_score               DOUBLE PRECISION NOT NULL CHECK (tag_score >= 0 AND tag_score <= 100),
    semantic_score          DOUBLE PRECISION NOT NULL CHECK (semantic_score >= 0 AND semantic_score <= 100),
    llm_score               DOUBLE PRECISION CHECK (llm_score >= 0 AND llm_score <= 100),
    reason                  TEXT NOT NULL,
    risk                    JSONB NOT NULL,
    evidence                JSONB NOT NULL,
    model                   TEXT NOT NULL,
    prompt_version          TEXT NOT NULL,
    dataset_version         TEXT NOT NULL,
    taxonomy_version        TEXT NOT NULL,
    embedding_model_version TEXT NOT NULL,
    is_stale                BOOLEAN NOT NULL DEFAULT false,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (achievement_id, demand_id, dataset_version, taxonomy_version, embedding_model_version)
);

-- ---------------------------------------------------------------------------
-- Evaluation sets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_query (
    query_id                    TEXT PRIMARY KEY,
    query_text                  TEXT NOT NULL,
    query_language              TEXT NOT NULL CHECK (query_language IN ('zh', 'en', 'mixed')),
    query_type                  TEXT NOT NULL CHECK (query_type IN ('zh_business', 'en_academic', 'cross_lingual', 'hard_negative')),
    target_tech_field           TEXT NOT NULL,
    candidate_achievement_ids   JSONB NOT NULL DEFAULT '[]'::jsonb,
    relevant_achievement_ids    JSONB,
    relevance_grades            JSONB,
    annotator                   TEXT,
    notes                       TEXT,
    dataset_version             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_label (
    pair_id             TEXT PRIMARY KEY,
    achievement_id      TEXT NOT NULL REFERENCES achievement(achievement_id) ON DELETE CASCADE,
    demand_id           TEXT NOT NULL REFERENCES demand(demand_id) ON DELETE CASCADE,
    relevance_grade     INTEGER CHECK (relevance_grade IN (0, 1, 2)),
    rationale           TEXT,
    hard_negative_type  TEXT CHECK (hard_negative_type IN ('cross_field', 'same_field_diff_scenario', 'same_field_trl_gap', 'lexical_trap', 'none')),
    annotator           TEXT,
    adjudication        TEXT,
    dataset_version     TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_raw_source_record_version ON raw_source_record (dataset_version);
CREATE INDEX IF NOT EXISTS ix_raw_source_record_tag ON raw_source_record (query_tag);

CREATE INDEX IF NOT EXISTS ix_achievement_version ON achievement (dataset_version);
CREATE INDEX IF NOT EXISTS ix_achievement_year ON achievement (publication_year);
CREATE INDEX IF NOT EXISTS ix_achievement_content_hash ON achievement (content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS ux_achievement_doi ON achievement (doi) WHERE doi IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_achievement_text_achievement ON achievement_text (achievement_id);
CREATE INDEX IF NOT EXISTS ix_achievement_text_hash ON achievement_text (text_hash);

CREATE INDEX IF NOT EXISTS ix_achievement_tag_lookup ON achievement_tag (dimension, code);
CREATE UNIQUE INDEX IF NOT EXISTS ux_achievement_tag_primary
    ON achievement_tag (achievement_id)
    WHERE dimension = 'tech_field' AND is_primary;

CREATE INDEX IF NOT EXISTS ix_achievement_extraction_run ON achievement_extraction (extraction_run_id);

CREATE INDEX IF NOT EXISTS ix_embedding_object ON embedding (object_type, object_id);
CREATE INDEX IF NOT EXISTS ix_embedding_vector_hnsw
    ON embedding USING hnsw ("vector" vector_cosine_ops);

CREATE INDEX IF NOT EXISTS ix_enterprise_industry ON enterprise (industry);
CREATE INDEX IF NOT EXISTS ix_enterprise_region ON enterprise (region);

CREATE INDEX IF NOT EXISTS ix_demand_enterprise ON demand (enterprise_id);
CREATE INDEX IF NOT EXISTS ix_demand_status ON demand (status);
CREATE INDEX IF NOT EXISTS ix_demand_version ON demand (dataset_version);

CREATE INDEX IF NOT EXISTS ix_demand_tag_lookup ON demand_tag (dimension, code);

CREATE INDEX IF NOT EXISTS ix_match_score_demand ON match_score (demand_id);
CREATE INDEX IF NOT EXISTS ix_match_score_achievement ON match_score (achievement_id);
CREATE INDEX IF NOT EXISTS ix_match_score_total ON match_score (total_score DESC);

CREATE INDEX IF NOT EXISTS ix_eval_query_version ON eval_query (dataset_version);
CREATE INDEX IF NOT EXISTS ix_eval_label_achievement ON eval_label (achievement_id);
CREATE INDEX IF NOT EXISTS ix_eval_label_demand ON eval_label (demand_id);

CREATE INDEX IF NOT EXISTS ix_pipeline_run_stage ON pipeline_run (stage, started_at);
CREATE INDEX IF NOT EXISTS ix_dataset_manifest_version ON dataset_manifest (dataset_version);
CREATE INDEX IF NOT EXISTS ix_dataset_manifest_run ON dataset_manifest (run_id);

COMMIT;
