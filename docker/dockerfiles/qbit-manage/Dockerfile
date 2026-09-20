# qbit_manage 4.13.0, revision 906af0f74818abaaa62f9f22e1e4e73ccb0d2bd5.
FROM ghcr.io/stuffanthings/qbit_manage@sha256:ea04167f627e506b3691304f4c639a52c05584cc9aea4af7ec87d4ed1299e7f5

ENV QBT_DRY_RUN=true

COPY patch_inactivity_policy.py /usr/local/libexec/qbit-manage-policy/
COPY tests /usr/local/libexec/qbit-manage-policy/tests/

RUN python3 /usr/local/libexec/qbit-manage-policy/patch_inactivity_policy.py /app \
    && PYTHONDONTWRITEBYTECODE=1 QBIT_MANAGE_SOURCE_ROOT=/app QBIT_MANAGE_REQUIRE_PATCHED=1 \
       python3 -m unittest discover -s /usr/local/libexec/qbit-manage-policy/tests -v
