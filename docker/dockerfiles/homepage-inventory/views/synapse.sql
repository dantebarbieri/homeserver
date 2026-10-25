CREATE OR REPLACE VIEW homepage_widget.stats WITH (security_barrier=true) AS
SELECT
  (SELECT COUNT(*) FROM public.users WHERE deactivated=0 AND is_guest=0) AS users,
  (SELECT COUNT(*) FROM public.rooms) AS rooms,
  (SELECT COUNT(DISTINCT user_id) FROM public.user_daily_visits
    WHERE timestamp >= EXTRACT(EPOCH FROM now() - interval '24 hours') * 1000) AS active;
