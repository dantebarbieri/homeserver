# qbit_manage 4.14.0, revision e6b2ba0b735b96cb153ef874d176ca6d0fffbf49.
FROM ghcr.io/stuffanthings/qbit_manage@sha256:0153204c727b8cd219c87cd22d5e5833e392436923577455e3c84ceb73835c7d

ENV QBT_DRY_RUN=true

COPY patch_inactivity_policy.py /usr/local/libexec/qbit-manage-policy/
COPY tests /usr/local/libexec/qbit-manage-policy/tests/

RUN python3 /usr/local/libexec/qbit-manage-policy/patch_inactivity_policy.py /app \
    && PYTHONDONTWRITEBYTECODE=1 QBIT_MANAGE_SOURCE_ROOT=/app QBIT_MANAGE_REQUIRE_PATCHED=1 \
       python3 -m unittest discover -s /usr/local/libexec/qbit-manage-policy/tests -v
