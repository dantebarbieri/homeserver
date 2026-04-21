# Pinned to match upstream opentopodata's own Dockerfile — rasterio==1.3.9
# (in opentopodata's requirements.txt) imports pkg_resources from setup.py,
# which breaks in pip's isolated build env on newer setuptools releases
# that come with later python:3.11-slim point releases.
FROM python:3.11.8-slim-bookworm
ARG OPENTOPODATA_REF=v1.9.0
RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential libgdal-dev gdal-bin \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Constrain pip's isolated build env to setuptools<70 — rasterio 1.3.9
# (pinned by opentopodata's requirements.txt) imports pkg_resources from
# its setup.py, which setuptools 70+ dropped from the default install.
RUN echo 'setuptools<70' > /tmp/build-constraints.txt
ENV PIP_CONSTRAINT=/tmp/build-constraints.txt
RUN git clone --depth 1 --branch ${OPENTOPODATA_REF} https://github.com/ajnisbet/opentopodata.git . \
    && pip install --no-cache-dir gdal=="$(gdal-config --version).*" \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn==22.0.0
# Copernicus GLO-30 and SRTM30m ship metadata siblings (blacklist.txt,
# tileList.txt, readme.html, etc.) in the dataset root; opentopodata's
# recursive glob treats every non-AUX file as a raster and fails config
# parsing when it hits one. Extend AUX_EXTENSIONS so these text/html
# metadata files are ignored.
RUN sed -i 's/^AUX_EXTENSIONS = \[\(.*\)\]$/AUX_EXTENSIONS = [\1, ".txt", ".html", ".md", ".json"]/' \
    /app/opentopodata/config.py \
    && grep -q '".html"' /app/opentopodata/config.py
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "60", "opentopodata.api:app"]
