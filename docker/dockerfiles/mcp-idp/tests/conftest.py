"""Pytest fixtures for mcp-idp tests."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mcp_idp.config import AppConfig
from mcp_idp.server import create_app

PEPPER = "test-pepper-must-be-at-least-thirty-two-bytes-long-yes-it-is"
ISSUER = "https://idp.test"
RESOURCE = "https://mcp-tcad.test"
PROXY_HEADER = "X-Test-User"


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        issuer=ISSUER,
        db_path=str(tmp_path / "db.sqlite"),
        keys_path=str(tmp_path / "keys.json"),
        pepper=PEPPER,
        resource_allowlist=(RESOURCE,),
        proxy_header_user=PROXY_HEADER,
        proxy_header_name="X-Test-Name",
        proxy_secret=None,
        cors_origins=("https://claude.ai",),
        access_token_ttl=3600,
        refresh_token_ttl=86400,
        auth_code_ttl=60,
        auth_request_ttl=600,
        dcr_max_redirect_uris=5,
        dcr_max_name_len=200,
        dcr_max_body_bytes=8 * 1024,
        dcr_allow_http_redirects=True,
    )


@pytest.fixture
def client(config: AppConfig) -> Iterator[TestClient]:
    app = create_app(config)
    with TestClient(app) as c:
        yield c
