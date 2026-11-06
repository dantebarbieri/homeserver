FROM python:3.13-alpine
# Not COPY --chmod: it also sets the mode of the /app dir it creates, locking out non-root users.
COPY *.py /app/
RUN chmod -R a+rX /app
WORKDIR /app
# Fail the build (an update then keeps the previous image) if a non-root user can't import the app.
RUN python -c "import os; os.setgroups([]); os.setgid(65534); os.setuid(65534); import plex_navidrome_sync"
# Healthy only if a run completed within two intervals (plus slack for a first run copying many plays).
HEALTHCHECK --interval=5m --timeout=10s --start-period=30m \
  CMD python -c "import json,os,time,sys; s=os.environ.get('STATE_DIR','/state'); i=int(os.environ.get('INTERVAL','900')); sys.exit(0 if time.time()-json.load(open(s+'/last_ok.json'))['at'] < 2*i+900 else 1)"
ENTRYPOINT ["python", "-u", "-c", "import plex_navidrome_sync; plex_navidrome_sync.main()"]
