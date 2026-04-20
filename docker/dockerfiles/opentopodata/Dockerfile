FROM python:3.11-slim
ARG OPENTOPODATA_REF=1.10.1
RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential libgdal-dev gdal-bin \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN git clone --depth 1 --branch ${OPENTOPODATA_REF} https://github.com/ajnisbet/opentopodata.git . \
    && pip install --no-cache-dir gdal=="$(gdal-config --version).*" \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn==22.0.0
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "60", "opentopodata.api:app"]
