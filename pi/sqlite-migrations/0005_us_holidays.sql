-- 0005_us_holidays.sql — US federal holidays with PTO-efficiency annotation.
-- Populated by the travel-holidays skill (Jan 1 annual cron job). The
-- planner uses pto_efficiency to pick windows that maximize time off for
-- minimum PTO burn.

CREATE TABLE us_holidays (
  holiday_date    TEXT PRIMARY KEY,      -- ISO 'YYYY-MM-DD'
  name            TEXT NOT NULL,
  pto_efficiency  TEXT NOT NULL CHECK (pto_efficiency IN
                    ('free_3day','bridge_4day','mega_9day','plain'))
);

CREATE INDEX idx_us_holidays_date ON us_holidays(holiday_date);
