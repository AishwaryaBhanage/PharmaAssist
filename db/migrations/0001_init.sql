-- PharmAssist v2 schema (PostgreSQL 16+, pgvector >= 0.7). This file is the contract every stream
-- codes against; stream A turns it into the Alembic baseline revision without changing names or types.
-- Conventions: timestamps are timestamptz in UTC; ids that come from content (document versions,
-- chunks, parents, figures) are the deterministic text ids the v1 pipeline already produces.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- identity
CREATE TABLE users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           text NOT NULL,
    password_hash   text NOT NULL,                       -- argon2id
    display_name    text NOT NULL DEFAULT '',
    role            text NOT NULL CHECK (role IN ('staff', 'admin')),
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_login_at   timestamptz
);
CREATE UNIQUE INDEX users_email_key ON users (lower(email));

CREATE TABLE refresh_tokens (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash      text NOT NULL UNIQUE,                -- sha256 of the opaque token; the token itself is never stored
    expires_at      timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz,
    replaced_by     uuid REFERENCES refresh_tokens (id)  -- rotation chain; reuse of a replaced token revokes the chain
);
CREATE INDEX refresh_tokens_user_idx ON refresh_tokens (user_id, expires_at);

-- ---------------------------------------------------------------- corpus
CREATE TABLE documents (
    id                text PRIMARY KEY,                  -- doc_id slug, e.g. va_dod_cpg_opioids_2022
    title             text NOT NULL,
    program           text NOT NULL,                     -- VA | Medicare Part D | NY Medicaid
    doc_type          text NOT NULL DEFAULT '',
    authority         text NOT NULL DEFAULT 'advisory',  -- binding | advisory
    publisher         text NOT NULL DEFAULT '',
    doc_date          text NOT NULL DEFAULT 'unknown',   -- as printed in the document: YYYY-MM or YYYY-MM-DD or unknown
    source_url        text,
    active_version_id text,                              -- FK added below (deferrable: versions reference documents)
    created_by        uuid REFERENCES users (id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id               text PRIMARY KEY,                   -- first 16 hex chars of the file's sha256
    document_id      text NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    sha256           text NOT NULL,
    s3_key           text NOT NULL,                      -- sources/<doc_id>/<sha16>/<file_name>
    file_name        text NOT NULL,
    content_type     text NOT NULL,
    bytes            bigint NOT NULL,
    pages            integer,                            -- NULL for spreadsheets
    status           text NOT NULL CHECK (status IN ('queued', 'parsing', 'extracting_figures', 'chunking',
                                                      'embedding', 'verifying', 'active', 'failed', 'superseded')),
    error            text,
    parser_version   text,
    chunker_version  text,
    embedder_model   text,
    embedding_dim    integer,
    chunk_count      integer NOT NULL DEFAULT 0,
    figure_count     integer NOT NULL DEFAULT 0,
    created_by       uuid REFERENCES users (id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    activated_at     timestamptz,
    UNIQUE (document_id, sha256)
);
ALTER TABLE documents ADD CONSTRAINT documents_active_version_fk
    FOREIGN KEY (active_version_id) REFERENCES document_versions (id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE parents (
    version_id    text NOT NULL REFERENCES document_versions (id) ON DELETE CASCADE,
    parent_id     text NOT NULL,                         -- v1 parent id (section-level unit)
    document_id   text NOT NULL,
    text          text NOT NULL,
    page_start    integer,
    page_end      integer,
    section_path  text[] NOT NULL DEFAULT '{}',
    metadata      jsonb NOT NULL DEFAULT '{}',           -- what v1 kept on a parent result (program, date, content_types, ...)
    PRIMARY KEY (version_id, parent_id)
);

CREATE TABLE chunks (
    version_id     text NOT NULL REFERENCES document_versions (id) ON DELETE CASCADE,
    chunk_id       text NOT NULL,                        -- v1 chunk id
    parent_id      text,
    document_id    text NOT NULL,
    text           text NOT NULL,                        -- what the model reads
    search_text    text NOT NULL,                        -- what is embedded and full-text indexed (heading path + text)
    page_start     integer,
    page_end       integer,
    section_path   text[] NOT NULL DEFAULT '{}',
    content_types  text[] NOT NULL DEFAULT '{}',         -- text | table | figure | flowchart | chart | caption
    extraction     text,                                 -- docling | vision | ocr
    figure_ids     text[] NOT NULL DEFAULT '{}',
    verification   text,                                 -- machine_interpreted | ocr_checked | reviewed
    program        text NOT NULL,
    authority      text NOT NULL,
    doc_date       text NOT NULL,
    metadata       jsonb NOT NULL DEFAULT '{}',          -- everything else v1 kept on the chunk
    embedding      halfvec(3072) NOT NULL,               -- text-embedding-3-large; halfvec: HNSW allows up to 4,000 dims
    tsv            tsvector GENERATED ALWAYS AS (to_tsvector('english', search_text)) STORED,
    PRIMARY KEY (version_id, chunk_id)
);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 128);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX chunks_document_idx ON chunks (document_id, version_id);
CREATE INDEX chunks_program_idx ON chunks (program);

CREATE TABLE figures (
    version_id   text NOT NULL REFERENCES document_versions (id) ON DELETE CASCADE,
    figure_id    text NOT NULL,
    document_id  text NOT NULL,
    page         integer NOT NULL,
    kind         text NOT NULL,                          -- flow_chart | chart | table_image | photo | ...
    title        text,
    status       text NOT NULL,                          -- machine_interpreted | ocr_checked | reviewed
    crop_s3_key  text,
    record       jsonb NOT NULL,                         -- the full v1 figure record (interpretation, checks, OCR)
    PRIMARY KEY (version_id, figure_id)
);
CREATE INDEX figures_page_idx ON figures (document_id, page);

CREATE TABLE table_rows (                                -- structured drug lookups (VA formulary, NY PDL)
    version_id  text NOT NULL REFERENCES document_versions (id) ON DELETE CASCADE,
    table_name  text NOT NULL CHECK (table_name IN ('va_formulary', 'ny_pdl')),
    row_no      integer NOT NULL,
    row         jsonb NOT NULL,
    PRIMARY KEY (version_id, table_name, row_no)
);
CREATE INDEX table_rows_drug_idx ON table_rows (table_name, lower(row->>'drug'));

CREATE TABLE ingestion_jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id    text NOT NULL REFERENCES document_versions (id) ON DELETE CASCADE,
    status        text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter', 'skipped')),
    attempt       integer NOT NULL DEFAULT 0,
    stage         text,                                  -- mirrors document_versions.status while running
    error         text,
    worker_id     text,
    queued_at     timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    heartbeat_at  timestamptz,
    finished_at   timestamptz,
    requested_by  uuid REFERENCES users (id)
);
CREATE INDEX ingestion_jobs_version_idx ON ingestion_jobs (version_id, queued_at DESC);

-- one row; generation increases whenever the set of active versions changes (cache invalidation key)
CREATE TABLE index_state (
    id          integer PRIMARY KEY CHECK (id = 1),
    generation  bigint NOT NULL DEFAULT 1,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO index_state (id) VALUES (1);

-- ---------------------------------------------------------------- conversations
CREATE TABLE conversations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title       text NOT NULL,                           -- first question, truncated
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_user_idx ON conversations (user_id, updated_at DESC);

CREATE TABLE messages (                                  -- one question and its answer
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    request_id       text NOT NULL UNIQUE,
    question         text NOT NULL,
    status           text NOT NULL,                      -- answered | no_answer (the only two the API returns)
    agent_status     text,                               -- the agent's own status before the no-answer rule
    answer           text NOT NULL,
    assumption       text,
    citations        jsonb NOT NULL DEFAULT '[]',        -- CitationOut[] as returned to the client
    conflicts        jsonb NOT NULL DEFAULT '[]',
    needs_review     boolean NOT NULL DEFAULT false,
    provider         text,                               -- openai | anthropic | cache
    model            text,
    fallback_used    boolean NOT NULL DEFAULT false,
    cached           boolean NOT NULL DEFAULT false,
    cache_hit_id     text,                               -- semantic cache entry id when cached
    cache_similarity double precision,
    latency_s        double precision,
    cost_usd         double precision,
    tokens           jsonb NOT NULL DEFAULT '{}',        -- {input, output, cache_read, cache_write}
    trace_id         text,                               -- LangSmith run id when tracing is on
    generation       bigint,                             -- index_state.generation answered against
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at);
CREATE INDEX messages_created_idx ON messages (created_at DESC);
CREATE INDEX messages_status_idx ON messages (status);

CREATE TABLE feedback (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id  uuid NOT NULL UNIQUE REFERENCES messages (id) ON DELETE CASCADE,   -- one rating per answer; a repeat replaces it
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    rating      text NOT NULL CHECK (rating IN ('helpful', 'unhelpful')),
    reason      text,                                    -- wrong | incomplete | outdated | unclear | other
    comment     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX feedback_rating_idx ON feedback (rating, created_at DESC);

-- durable copy of the day's counters (Valkey is authoritative for admission; this survives a cache flush)
CREATE TABLE usage_days (
    day        date PRIMARY KEY,
    questions  integer NOT NULL DEFAULT 0,
    spend_usd  double precision NOT NULL DEFAULT 0
);
