CREATE TABLE IF NOT EXISTS canonical_questions (
  id TEXT PRIMARY KEY,
  canonical_fingerprint TEXT NOT NULL,
  representative_item_id TEXT NOT NULL,
  stem_latex TEXT NOT NULL DEFAULT '',
  answer_latex TEXT NOT NULL DEFAULT '',
  analysis_latex TEXT NOT NULL DEFAULT '',
  question_type TEXT NOT NULL DEFAULT '',
  difficulty INTEGER CHECK (difficulty >= 1 AND difficulty <= 5),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reverted')),
  created_from_group_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS question_variants (
  id TEXT PRIMARY KEY,
  canonical_question_id TEXT NOT NULL REFERENCES canonical_questions(id) ON DELETE CASCADE,
  question_id TEXT,
  paper_id TEXT NOT NULL,
  variant_type TEXT NOT NULL DEFAULT 'candidate',
  source_position_key TEXT NOT NULL,
  text_fingerprint TEXT NOT NULL DEFAULT '',
  latex_fingerprint TEXT NOT NULL DEFAULT '',
  asset_signature TEXT NOT NULL DEFAULT '',
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonicalization_events (
  id TEXT PRIMARY KEY,
  canonical_question_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('created', 'reverted', 'reactivated')),
  payload_json JSONB NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_canonical_group ON canonical_questions(created_from_group_id);
CREATE INDEX IF NOT EXISTS idx_variants_canonical ON question_variants(canonical_question_id);
CREATE INDEX IF NOT EXISTS idx_events_canonical ON canonicalization_events(canonical_question_id);
