FROM python:3.13-alpine
# Not COPY --chmod: it also sets the mode of the /app dir it creates, locking out non-root users.
COPY *.py /app/
RUN chmod -R a+rX /app
WORKDIR /app
# Fail the build (an update then keeps the previous image) if a non-root user can't import the app.
RUN python -c "import os; os.setgroups([]); os.setgid(65534); os.setuid(65534); import plex_navidrome_sync"
# Healthy while awaiting credentials; once configured, require a recent successful run.
HEALTHCHECK --interval=5m --timeout=10s --start-period=30m \
  CMD python -c "import sys,plex_navidrome_sync; sys.exit(plex_navidrome_sync.healthcheck())"
ENTRYPOINT ["python", "-u", "-c", "import plex_navidrome_sync; plex_navidrome_sync.main()"]
