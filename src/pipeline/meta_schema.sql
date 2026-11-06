-- Own schema for run control and change tracking. Lives next to the MOSIDI
-- tables in the same database and never touches them.
CREATE SCHEMA IF NOT EXISTS pipeline_meta;

CREATE TABLE IF NOT EXISTS pipeline_meta.runs (
	run_id      TEXT PRIMARY KEY,
	started_at  TIMESTAMPTZ NOT NULL,
	finished_at TIMESTAMPTZ,
	status      TEXT NOT NULL,
	report      JSONB
);

-- Last imported state per source and business key; basis for the diff.
CREATE TABLE IF NOT EXISTS pipeline_meta.record_state (
	source      TEXT NOT NULL,
	record_key  TEXT NOT NULL,
	record_hash TEXT NOT NULL,
	updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
	PRIMARY KEY (source, record_key)
);
