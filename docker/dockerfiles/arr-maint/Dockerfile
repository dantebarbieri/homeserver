FROM python:3.13-alpine
# COPY keeps the checkout's modes, and the non-root user this runs as can't read a
# 0600 file or enter a 0700 dir. Not COPY --chmod=0644: it also gave the /app dir it
# creates mode 0644, which nobody but root can enter.
COPY *.py /app/
RUN chmod -R a+rX /app
WORKDIR /app
# Fail the build (an update then keeps the previous image) if a non-root user can't import the app.
RUN python -c "import os; os.setgroups([]); os.setgid(65534); os.setuid(65534); import arr_maint"
# Healthy only if a run completed within two intervals (plus slack for long imports).
HEALTHCHECK --interval=5m --timeout=10s --start-period=15m \
  CMD python -c "import json,os,time,sys; s=os.environ.get('STATE_DIR','/state'); i=int(os.environ.get('INTERVAL','1800')); sys.exit(0 if time.time()-json.load(open(s+'/last_ok.json'))['at'] < 2*i+900 else 1)"
# APP (lidarr, radarr or sonarr) selects the rules module.
ENTRYPOINT ["python", "-u", "-c", "import arr_maint; arr_maint.main()"]
