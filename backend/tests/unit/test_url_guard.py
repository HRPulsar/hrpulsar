"""SSRF guard for tenant-supplied endpoint URLs (``app/core/url_guard.py``).

IP-literal hosts only — no DNS in unit tests. The saas gate is the whole
point: tenant-set base_url must not reach inside the platform perimeter,
while self-hosted installs keep private endpoints (LAN Ollama) working.
"""

import pytest
from app.config import settings
from app.core.errors import AppError
from app.core.url_guard import ensure_public_base_url


async def test_saas_rejects_private_and_malformed(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    for url in (
        "http://127.0.0.1:11434/v1",
        "http://10.0.0.5/v1",
        "http://192.168.1.20/v1",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/v1",
        "http://0.0.0.0/v1",
        "ftp://example.com/",
        "http://",
    ):
        with pytest.raises(AppError) as err:
            await ensure_public_base_url(url, error_code="llm_base_url_not_public")
        assert err.value.code == "llm_base_url_not_public", url


async def test_saas_allows_public_host(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    await ensure_public_base_url(
        "https://8.8.8.8/v1", error_code="llm_base_url_not_public"
    )


async def test_onprem_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "onprem")
    await ensure_public_base_url(
        "http://127.0.0.1:11434/v1", error_code="llm_base_url_not_public"
    )
