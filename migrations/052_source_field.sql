-- Session 52 — V1/V2 data-mode toggle.
-- Add `source` column to every projection table touched by the V1/V2 filter.
-- All five tables were created by migrations/009_projection_views.sql (S09).
-- Idempotent: IF NOT EXISTS on every column add so re-runs are safe.
--
-- Default 'seed' backfills every existing projected row to demo-portfolio
-- provenance. New rows written by the intake flow set source='real'
-- explicitly; the projection writers pass the field through unchanged.

ALTER TABLE ai_systems
    ADD COLUMN IF NOT EXISTS data_source TEXT NOT NULL DEFAULT 'seed';

ALTER TABLE eval_runs
    ADD COLUMN IF NOT EXISTS data_source TEXT NOT NULL DEFAULT 'seed';

ALTER TABLE findings
    ADD COLUMN IF NOT EXISTS data_source TEXT NOT NULL DEFAULT 'seed';

ALTER TABLE release_decisions
    ADD COLUMN IF NOT EXISTS data_source TEXT NOT NULL DEFAULT 'seed';

ALTER TABLE policy_evaluations
    ADD COLUMN IF NOT EXISTS data_source TEXT NOT NULL DEFAULT 'seed';

-- Helpful indexes for V2-mode list scans (small selectivity, but the
-- portfolio table grows linearly with real customers).
CREATE INDEX IF NOT EXISTS idx_ai_systems_data_source ON ai_systems(data_source);
CREATE INDEX IF NOT EXISTS idx_findings_data_source ON findings(data_source);
