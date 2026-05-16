CREATE TABLE IF NOT EXISTS papers (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT 'math',
  grade TEXT,
  source TEXT,
  pdf_url TEXT NOT NULL,
  pdf_type TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL DEFAULT 'pending',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS parse_runs (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  engine TEXT NOT NULL,
  engine_version TEXT,
  config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_output_url TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS question_blocks (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  parse_run_id TEXT REFERENCES parse_runs(id) ON DELETE SET NULL,
  question_number TEXT NOT NULL,
  section_title TEXT,
  raw_markdown TEXT NOT NULL,
  pages JSONB NOT NULL DEFAULT '[]'::jsonb,
  bbox_json JSONB,
  split_confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  needs_review BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY,
  question_block_id TEXT REFERENCES question_blocks(id) ON DELETE SET NULL,
  subject TEXT NOT NULL DEFAULT 'math',
  grade TEXT,
  question_type TEXT NOT NULL,
  stem_latex TEXT NOT NULL,
  answer_latex TEXT NOT NULL DEFAULT '',
  analysis_latex TEXT NOT NULL DEFAULT '',
  difficulty INTEGER CHECK (difficulty IS NULL OR difficulty BETWEEN 1 AND 5),
  quality_status TEXT NOT NULL DEFAULT 'draft',
  review_status TEXT NOT NULL DEFAULT 'draft',
  source_location_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  knowledge_points JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS choices (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  content_latex TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (question_id, label)
);

CREATE TABLE IF NOT EXISTS question_assets (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  storage_url TEXT NOT NULL,
  page INTEGER,
  bbox_json JSONB,
  caption TEXT NOT NULL DEFAULT '',
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quality_reports (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  rule_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
  render_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
  model_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
  overall_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  needs_review BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parse_runs_paper_id ON parse_runs(paper_id);
CREATE INDEX IF NOT EXISTS idx_question_blocks_paper_id ON question_blocks(paper_id);
CREATE INDEX IF NOT EXISTS idx_questions_question_block_id ON questions(question_block_id);
CREATE INDEX IF NOT EXISTS idx_questions_review_status ON questions(review_status);
CREATE INDEX IF NOT EXISTS idx_question_assets_question_id ON question_assets(question_id);
CREATE INDEX IF NOT EXISTS idx_quality_reports_question_id ON quality_reports(question_id);

