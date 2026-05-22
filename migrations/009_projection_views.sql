-- Migration 009: Postgres event projection tables
-- Re-runnable: all CREATE statements use IF NOT EXISTS.
-- Hybrid schema: typed hot columns + JSONB for remaining payload.
-- Source of truth remains data/events.jsonl; these are read-side replicas.

-- ---------------------------------------------------------------------------
-- ai_systems — one row per AI system (AGENT_CREATED events)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ai_systems (
    system_id   TEXT        PRIMARY KEY,
    name        TEXT,
    owner       TEXT,
    risk_tier   TEXT,
    created_at  TIMESTAMPTZ,
    metadata    JSONB
);

CREATE INDEX IF NOT EXISTS idx_ai_systems_owner
    ON ai_systems (owner);

CREATE INDEX IF NOT EXISTS idx_ai_systems_risk_tier
    ON ai_systems (risk_tier);

CREATE INDEX IF NOT EXISTS idx_ai_systems_metadata_gin
    ON ai_systems USING GIN (metadata);

-- ---------------------------------------------------------------------------
-- eval_runs — one row per evaluation run (EVAL_RUN_STARTED / EVAL_RUN_COMPLETED)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id      TEXT        PRIMARY KEY,
    system_id   TEXT,
    status      TEXT,
    pass_rate   NUMERIC,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    metrics     JSONB
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_system_id
    ON eval_runs (system_id);

CREATE INDEX IF NOT EXISTS idx_eval_runs_status
    ON eval_runs (status);

CREATE INDEX IF NOT EXISTS idx_eval_runs_metrics_gin
    ON eval_runs USING GIN (metrics);

-- ---------------------------------------------------------------------------
-- findings — one row per finding (FINDING_CREATED / FINDING_STATUS_CHANGED)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS findings (
    finding_id  TEXT        PRIMARY KEY,
    system_id   TEXT,
    severity    TEXT,
    status      TEXT,
    created_at  TIMESTAMPTZ,
    payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_findings_system_id
    ON findings (system_id);

CREATE INDEX IF NOT EXISTS idx_findings_severity
    ON findings (severity);

CREATE INDEX IF NOT EXISTS idx_findings_status
    ON findings (status);

CREATE INDEX IF NOT EXISTS idx_findings_payload_gin
    ON findings USING GIN (payload);

-- ---------------------------------------------------------------------------
-- release_decisions — one row per release gate decision (RELEASE_DECISION_RECORDED)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS release_decisions (
    decision_id  TEXT        PRIMARY KEY,
    system_id    TEXT,
    decision     TEXT,
    decided_at   TIMESTAMPTZ,
    gate_results JSONB
);

CREATE INDEX IF NOT EXISTS idx_release_decisions_system_id
    ON release_decisions (system_id);

CREATE INDEX IF NOT EXISTS idx_release_decisions_decision
    ON release_decisions (decision);

CREATE INDEX IF NOT EXISTS idx_release_decisions_gate_results_gin
    ON release_decisions USING GIN (gate_results);

-- ---------------------------------------------------------------------------
-- policy_evaluations — one row per policy eval (POLICY_EVALUATED)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS policy_evaluations (
    eval_id      TEXT        PRIMARY KEY,
    system_id    TEXT,
    category     TEXT,
    decision     TEXT,
    evaluated_at TIMESTAMPTZ,
    inputs       JSONB
);

CREATE INDEX IF NOT EXISTS idx_policy_evaluations_system_id
    ON policy_evaluations (system_id);

CREATE INDEX IF NOT EXISTS idx_policy_evaluations_category
    ON policy_evaluations (category);

CREATE INDEX IF NOT EXISTS idx_policy_evaluations_decision
    ON policy_evaluations (decision);

CREATE INDEX IF NOT EXISTS idx_policy_evaluations_inputs_gin
    ON policy_evaluations USING GIN (inputs);

-- ---------------------------------------------------------------------------
-- projection_state — idempotency tracking: one row per projected event_id
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS projection_state (
    event_id    TEXT PRIMARY KEY,
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projection_state_projected_at
    ON projection_state (projected_at);
