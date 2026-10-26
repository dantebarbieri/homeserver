FROM python:3.13-alpine
COPY sonarr_maint.py /app/sonarr_maint.py
# Healthy only if a run completed within two intervals (plus slack for long imports).
HEALTHCHECK --interval=5m --timeout=10s --start-period=15m \
  CMD python -c "import json,os,time,sys; s=os.environ.get('STATE_DIR','/state'); i=int(os.environ.get('INTERVAL','1800')); sys.exit(0 if time.time()-json.load(open(s+'/last_ok.json'))['at'] < 2*i+900 else 1)"
ENTRYPOINT ["python", "-u", "/app/sonarr_maint.py"]
