FROM python:3.13-alpine
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY music_cover_fallback.py /app/
RUN chmod -R a+rX /app
WORKDIR /app
RUN python -c "import os; os.setgroups([]); os.setgid(65534); os.setuid(65534); import music_cover_fallback"
HEALTHCHECK --interval=5m --timeout=10s --start-period=30m \
  CMD python -c "import sys,music_cover_fallback as app; sys.exit(app.healthcheck())"
ENTRYPOINT ["python", "-u", "music_cover_fallback.py"]
