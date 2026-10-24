# qbit_manage 4.14.0, revision e6b2ba0b735b96cb153ef874d176ca6d0fffbf49.
FROM ghcr.io/stuffanthings/qbit_manage@sha256:0153204c727b8cd219c87cd22d5e5833e392436923577455e3c84ceb73835c7d

ENV QBT_DRY_RUN=true

# qbit_manage gates on qbittorrent-api's max supported qBittorrent version;
# 2026.10.1 (same pin as upstream develop) adds qBittorrent 5.3.0.
RUN pip install --no-cache-dir --no-deps qbittorrent-api==2026.10.1 \
    && python3 -c "from qbittorrentapi import Version; assert Version.is_app_version_supported('v5.3.0')"

COPY patch_inactivity_policy.py /usr/local/libexec/qbit-manage-policy/
COPY tests /usr/local/libexec/qbit-manage-policy/tests/

RUN python3 /usr/local/libexec/qbit-manage-policy/patch_inactivity_policy.py /app \
    && PYTHONDONTWRITEBYTECODE=1 QBIT_MANAGE_SOURCE_ROOT=/app QBIT_MANAGE_REQUIRE_PATCHED=1 \
       python3 -m unittest discover -s /usr/local/libexec/qbit-manage-policy/tests -v
