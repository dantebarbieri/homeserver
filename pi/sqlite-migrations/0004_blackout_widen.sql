-- 0004_blackout_widen.sql — widen the Feb 2027 blackout to the full
-- Jan 15–Mar 31 2027 wedding + buffer window the planner must never
-- schedule trips into.

UPDATE blackouts
SET start_date = '2027-01-15',
    end_date   = '2027-03-31',
    reason     = 'wedding + buffer'
WHERE reason   = 'Feb 2027 personal commitment'
  AND start_date = '2027-02-01'
  AND end_date   = '2027-02-28';
