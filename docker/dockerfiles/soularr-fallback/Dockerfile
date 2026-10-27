FROM python:3.13-alpine
COPY soularr_fallback.py /app/
WORKDIR /app
# Healthy only if a run completed within two intervals (plus slack for long search passes).
HEALTHCHECK --interval=5m --timeout=10s --start-period=1h \
  CMD python -c "import json,os,time,sys; i=int(os.environ.get('INTERVAL','3600')); sys.exit(0 if time.time()-json.load(open(os.environ.get('STATE_DIR','/state')+'/last_ok.json'))['at'] < 2*i+3600 else 1)"
ENTRYPOINT ["python", "-u", "soularr_fallback.py"]
