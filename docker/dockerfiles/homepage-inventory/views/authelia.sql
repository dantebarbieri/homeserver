CREATE OR REPLACE VIEW homepage_widget.stats WITH (security_barrier=true) AS
SELECT
  (SELECT COUNT(*) FROM public.authentication_logs
    WHERE successful AND time >= now() - interval '24 hours') AS successful,
  (SELECT COUNT(*) FROM public.authentication_logs
    WHERE NOT successful AND time >= now() - interval '24 hours') AS failed,
  (SELECT COUNT(*) FROM public.totp_configurations) AS totp,
  (SELECT COUNT(*) FROM public.webauthn_credentials) AS passkeys;
