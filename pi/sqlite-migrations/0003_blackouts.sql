-- 0003_blackouts.sql — hard date-range constraints the planner must respect.
-- Modeled as a table (not a prompt instruction) so it survives any prompt
-- regression and can be queried programmatically.

CREATE TABLE blackouts (
  id          INTEGER PRIMARY KEY,
  reason      TEXT NOT NULL,
  start_date  TEXT NOT NULL,
  end_date    TEXT NOT NULL,
  CHECK (start_date <= end_date)
);

INSERT INTO blackouts (reason, start_date, end_date) VALUES
  ('Feb 2027 personal commitment', '2027-02-01', '2027-02-28');
