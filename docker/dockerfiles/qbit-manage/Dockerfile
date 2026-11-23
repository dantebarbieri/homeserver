# qbit_manage 4.15.0, revision 1732b2b1acb9a3ea4c44b83c822e675d1bbe7fed.
FROM ghcr.io/stuffanthings/qbit_manage@sha256:f8db47d6533bac7c7f71d367545c5059d7228bcca188db1e059dbf4a693d8362

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
