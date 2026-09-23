-- Job Hunter schema
-- One row per search run in `runs`, carried through its lifecycle in `status`:
-- new -> researching -> jobs_found -> resume_ready -> presented
-- (rejected / failed can happen from most states)
--
-- One row per discovered listing in `jobs`, linked to the run that found it.
-- Folder is truth for generated content (resume.pdf, job-posting.json,
-- match-notes.md live under jobs/<id>-<company-slug>/) -- this DB only ever
-- stores paths into that folder, never file bytes or long-form copy.
-- Resumes are PDF only: there is no Markdown resume anywhere in the pipeline.
--
-- Single-user app: one operator, one CV, no accounts/login table.

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),

  role TEXT NOT NULL,
  seniority TEXT,
  location TEXT,
  target_companies TEXT,           -- optional free-text override for this run

  status TEXT NOT NULL DEFAULT 'new',
  error_message TEXT,

  researching_at TEXT,
  jobs_found_at TEXT,
  resume_ready_at TEXT,
  presented_at TEXT,
  rejected_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),

  company TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,               -- posting URL on the company's own careers page
  location TEXT,
  source TEXT,                     -- 'target-list' | 'career-page-discovered'
  posted_date TEXT,                -- YYYY-MM-DD; NULL means the date could not be verified

  match_score INTEGER,             -- 0-100
  match_notes TEXT,

  status TEXT NOT NULL DEFAULT 'found',   -- found | resume_ready | skipped

  job_folder TEXT,                 -- jobs/<id>-<company-slug>/
  resume_pdf_path TEXT,
  error_message TEXT,

  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  job_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  event TEXT NOT NULL,
  message TEXT,
  FOREIGN KEY (run_id) REFERENCES runs(id),
  FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- System settings, key/value (e.g. 'onboarded').
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
