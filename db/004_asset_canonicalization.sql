CREATE TABLE IF NOT EXISTS raw_assets (
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL,
  page INTEGER NOT NULL,
  bbox_json JSONB NOT NULL,
  asset_type TEXT NOT NULL,
  source_element_id TEXT NOT NULL,
  crop_path TEXT,
  storage_url TEXT,
  perceptual_hash TEXT,
  content_hash TEXT NOT NULL,
  width DOUBLE PRECISION,
  height DOUBLE PRECISION,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS question_asset_links (
  id TEXT PRIMARY KEY,
  question_id TEXT,
  canonical_question_id TEXT,
  raw_asset_id TEXT NOT NULL REFERENCES raw_assets(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'figure',
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  needs_review BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical_assets (
  id TEXT PRIMARY KEY,
  asset_fingerprint TEXT NOT NULL,
  representative_raw_asset_id TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  storage_url TEXT,
  perceptual_hash TEXT,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reverted')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asset_variants (
  id TEXT PRIMARY KEY,
  canonical_asset_id TEXT NOT NULL REFERENCES canonical_assets(id) ON DELETE CASCADE,
  raw_asset_id TEXT NOT NULL REFERENCES raw_assets(id) ON DELETE CASCADE,
  transform_json JSONB NOT NULL DEFAULT '{}',
  similarity DOUBLE PRECISION,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_assets_paper ON raw_assets(paper_id);
CREATE INDEX IF NOT EXISTS idx_raw_assets_content_hash ON raw_assets(content_hash);
CREATE INDEX IF NOT EXISTS idx_question_asset_links_question ON question_asset_links(question_id);
CREATE INDEX IF NOT EXISTS idx_question_asset_links_canonical ON question_asset_links(canonical_question_id);
CREATE INDEX IF NOT EXISTS idx_canonical_assets_fingerprint ON canonical_assets(asset_fingerprint);
CREATE INDEX IF NOT EXISTS idx_asset_variants_canonical ON asset_variants(canonical_asset_id);
