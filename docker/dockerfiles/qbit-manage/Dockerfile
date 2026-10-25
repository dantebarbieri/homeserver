# qbit_manage 4.14.0, revision e6b2ba0b735b96cb153ef874d176ca6d0fffbf49.
FROM ghcr.io/stuffanthings/qbit_manage@sha256:0153204c727b8cd219c87cd22d5e5833e392436923577455e3c84ceb73835c7d

ENV QBT_DRY_RUN=true

# qbit_manage refuses qBittorrent versions newer than its bundled qbittorrent-api
# knows about, while qBittorrent itself tracks :latest. Install the newest
# qbittorrent-api on every build so the nightly `docker compose build --pull`
# follows qBittorrent. ADD of the PyPI metadata busts the layer cache only when
# a new release is published. If anything below fails, the build fails and the
# previous image keeps running.
ADD https://pypi.org/pypi/qbittorrent-api/json /tmp/qbittorrent-api.json
RUN bundled="$(python3 -c 'from qbittorrentapi import Version; print(Version.latest_supported_app_version())')" \
    && pip install --no-cache-dir --upgrade qbittorrent-api \
    && rm /tmp/qbittorrent-api.json \
    && cd /app && python3 -c "import modules.qbittorrent" \
    && python3 -c "from qbittorrentapi import Version; import sys; print('qbittorrent-api supports up to', Version.latest_supported_app_version()); sys.exit(not Version.is_app_version_supported('$bundled'))"

COPY patch_inactivity_policy.py /usr/local/libexec/qbit-manage-policy/
COPY tests /usr/local/libexec/qbit-manage-policy/tests/

RUN python3 /usr/local/libexec/qbit-manage-policy/patch_inactivity_policy.py /app \
    && PYTHONDONTWRITEBYTECODE=1 QBIT_MANAGE_SOURCE_ROOT=/app QBIT_MANAGE_REQUIRE_PATCHED=1 \
       python3 -m unittest discover -s /usr/local/libexec/qbit-manage-policy/tests -v

# Runs after the policy tests, which verify the unmodified share_limits.py hash.
COPY patch_share_limits_mode.py /usr/local/libexec/qbit-manage-policy/
RUN python3 /usr/local/libexec/qbit-manage-policy/patch_share_limits_mode.py /app \
    && cd /app && python3 -c "from modules.core.share_limits import _parse_api_version as p; assert p('2.15.3') >= (2, 15, 3) > p('2.15.2')"
