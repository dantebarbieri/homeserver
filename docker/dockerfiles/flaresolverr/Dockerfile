FROM ghcr.io/flaresolverr/flaresolverr:latest
# Upstream ships Debian's Chromium, which trails Chrome stable by several releases. Replace
# it, and the driver FlareSolverr patches at start-up, with Chrome for Testing stable and its
# matching chromedriver on every nightly `docker compose build --pull`; ADD of the release
# catalog busts this layer only when Google publishes a release.
USER root
ADD https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json /tmp/chrome-for-testing.json
COPY install-chrome.py /tmp/install-chrome.py
# undetected_chromedriver picks one of several candidate names from a set, so the old
# /usr/bin/chromium must stay the only candidate, now pointing at the new Chrome.
RUN set -eu; \
    python3 /tmp/install-chrome.py /tmp/chrome-for-testing.json 158.0.8127.36; \
    chown flaresolverr:flaresolverr /app/chromedriver; \
    ln -sf /opt/chrome/chrome /usr/bin/chromium; \
    rm -rf /tmp/chrome-for-testing.json /tmp/install-chrome.py /tmp/chromedriver-linux64; \
    chrome="$(/usr/bin/chromium --version | grep -oE '[0-9]+(\.[0-9]+){3}')"; \
    driver="$(/app/chromedriver --version | grep -oE '[0-9]+(\.[0-9]+){3}' | head -n 1)"; \
    echo "Chrome $chrome, chromedriver $driver"; \
    test "$chrome" = "$driver"
USER flaresolverr
