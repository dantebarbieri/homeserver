CREATE OR REPLACE VIEW homepage_widget.stats WITH (security_barrier=true) AS
SELECT
  COUNT(*) FILTER (WHERE status='queued') AS queued,
  COUNT(*) FILTER (WHERE status='processing') AS running,
  COUNT(*) FILTER (WHERE status='completed' AND completed_at >= now() - interval '24 hours') AS completed,
  COUNT(*) FILTER (WHERE status='failed' AND completed_at >= now() - interval '24 hours') AS failed
FROM public.jobs;
