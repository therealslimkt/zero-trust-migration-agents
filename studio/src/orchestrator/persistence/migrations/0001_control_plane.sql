CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agents (
  id text PRIMARY KEY,
  display_name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('build', 'product')),
  model_policy text NOT NULL,
  status text NOT NULL DEFAULT 'idle',
  manifest jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_status (
  provider_id text PRIMARY KEY,
  status jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id text PRIMARY KEY,
  trace_id text NOT NULL,
  owner_agent_id text NOT NULL,
  reviewer_agent_id text,
  status text NOT NULL,
  envelope jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tasks_status_updated_idx ON tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS events (
  event_id text PRIMARY KEY,
  trace_id text NOT NULL,
  task_id text NOT NULL,
  event_type text NOT NULL,
  event jsonb NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS events_task_created_idx ON events(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS events_trace_created_idx ON events(trace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id text PRIMARY KEY,
  task_id text NOT NULL,
  requesting_agent_id text NOT NULL,
  status text NOT NULL,
  request jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id text PRIMARY KEY,
  task_id text NOT NULL,
  created_by text NOT NULL,
  record jsonb NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  feedback_id text PRIMARY KEY,
  task_id text NOT NULL,
  subject_agent_id text NOT NULL,
  source text NOT NULL,
  sentiment text NOT NULL,
  score double precision,
  summary text NOT NULL,
  evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  promotion_status text NOT NULL DEFAULT 'raw',
  created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS feedback_agent_created_idx ON feedback(subject_agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS feedback_promotion_idx ON feedback(promotion_status, created_at DESC);

CREATE TABLE IF NOT EXISTS eval_runs (
  eval_run_id text PRIMARY KEY,
  task_id text NOT NULL,
  agent_id text NOT NULL,
  status text NOT NULL,
  score double precision,
  run jsonb NOT NULL,
  started_at timestamptz NOT NULL,
  completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS memory_candidates (
  candidate_id text PRIMARY KEY,
  agent_id text NOT NULL,
  lesson text NOT NULL,
  evidence_feedback_ids jsonb NOT NULL,
  confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  status text NOT NULL DEFAULT 'proposed',
  created_at timestamptz NOT NULL,
  decided_at timestamptz,
  decided_by text
);

CREATE TABLE IF NOT EXISTS semantic_memory (
  memory_id text PRIMARY KEY,
  agent_id text NOT NULL,
  lesson text NOT NULL,
  evidence_feedback_ids jsonb NOT NULL,
  embedding vector,
  promoted_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS routing_outcomes (
  routing_outcome_id text PRIMARY KEY,
  task_id text NOT NULL,
  agent_id text NOT NULL,
  provider_id text NOT NULL,
  model text NOT NULL,
  result_status text NOT NULL,
  quality_score double precision,
  duration_ms bigint NOT NULL,
  estimated_cost_usd numeric(12, 6),
  created_at timestamptz NOT NULL
);

