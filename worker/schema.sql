-- D1 schema for the semantic-citations Worker.
-- Apply with: npx wrangler d1 execute semantic-citations --remote --file schema.sql

-- A looked-up paper (title, abstract, citing count), under "lookup:<doi>" and "paper:<openalex id>".
CREATE TABLE IF NOT EXISTS papers (key TEXT PRIMARY KEY, json TEXT NOT NULL, expires INTEGER NOT NULL);

-- The works citing a paper, 100 per page, most-cited first.
CREATE TABLE IF NOT EXISTS pages (target TEXT NOT NULL, page INTEGER NOT NULL, json TEXT NOT NULL, expires INTEGER NOT NULL, PRIMARY KEY (target, page));

-- The labelled citations of `target` found in `work`. Kept until the pipeline version changes.
CREATE TABLE IF NOT EXISTS results (version TEXT NOT NULL, target TEXT NOT NULL, work TEXT NOT NULL, json TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY (version, target, work));

-- New papers labelled per UTC day, for the daily spend cap.
CREATE TABLE IF NOT EXISTS counters (day TEXT PRIMARY KEY, n INTEGER NOT NULL);

-- When each arXiv host may next be fetched, so all visitors share one polite queue.
CREATE TABLE IF NOT EXISTS pace (host TEXT PRIMARY KEY, next_at INTEGER NOT NULL);
