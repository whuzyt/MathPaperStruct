-- ADR 004: Duplicate Review Queue v1
-- Stores fingerprint-based duplicate candidate groups for human review.
-- All tables use IF NOT EXISTS — safe to re-run db init.

CREATE TABLE IF NOT EXISTS duplicate_candidate_groups (
  id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  fingerprint_type TEXT NOT NULL DEFAULT 'text',
  candidate_count INTEGER NOT NULL DEFAULT 0,
  max_similarity DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS duplicate_candidate_items (
  id TEXT PRIMARY KEY,
  group_id TEXT NOT NULL REFERENCES duplicate_candidate_groups(id) ON DELETE CASCADE,
  block_id TEXT NOT NULL,
  question_id TEXT,
  paper_id TEXT NOT NULL,
  section_path TEXT NOT NULL DEFAULT '',
  question_number TEXT NOT NULL,
  source_position_key TEXT NOT NULL,
  text_fingerprint TEXT NOT NULL DEFAULT '',
  latex_fingerprint TEXT NOT NULL DEFAULT '',
  asset_signature TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS duplicate_review_decisions (
  id TEXT PRIMARY KEY,
  group_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('same', 'variant', 'unrelated', 'unsure')),
  canonical_question_id TEXT,
  reviewer TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dup_items_group
  ON duplicate_candidate_items(group_id);
CREATE INDEX IF NOT EXISTS idx_dup_items_fp
  ON duplicate_candidate_items(text_fingerprint);
CREATE INDEX IF NOT EXISTS idx_dup_decisions_group
  ON duplicate_review_decisions(group_id);
