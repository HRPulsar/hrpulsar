"""Outbound-URL guard for tenant-supplied endpoints (SSRF).

On saas deployments a tenant-configured URL turns into a server-side
request from inside the platform perimeter, so its host must resolve to
public addresses only. On self-hosted installs private endpoints are the
point (a LAN Ollama, an in-rack vLLM) — the guard is a no-op there.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import status

from app.config import settings
from app.core.errors import AppError


async def ensure_public_base_url(url: str, *, error_code: str) -> None:
    if settings.deployment_mode != "saas":
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AppError(error_code, status.HTTP_400_BAD_REQUEST)
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise AppError(error_code, status.HTTP_400_BAD_REQUEST) from exc
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise AppError(error_code, status.HTTP_400_BAD_REQUEST)
