FROM python:3.13-alpine
# COPY keeps the checkout's modes, and the non-root user this runs as can't read a
# 0600 file or enter a 0700 dir. Not COPY --chmod=0644: it also gave the /app dir it
# creates mode 0644, which nobody but root can enter.
COPY soularr_fallback.py /app/
RUN chmod -R a+rX /app
WORKDIR /app
# Fail the build (an update then keeps the previous image) if a non-root user can't import the app.
RUN python -c "import os; os.setgroups([]); os.setgid(65534); os.setuid(65534); import soularr_fallback"
# Healthy only if a run completed within two intervals (plus slack for long search passes).
HEALTHCHECK --interval=5m --timeout=10s --start-period=1h \
  CMD python -c "import json,os,time,sys; i=int(os.environ.get('INTERVAL','3600')); sys.exit(0 if time.time()-json.load(open(os.environ.get('STATE_DIR','/state')+'/last_ok.json'))['at'] < 2*i+3600 else 1)"
ENTRYPOINT ["python", "-u", "soularr_fallback.py"]
