"""HRP-990: every image in the self-hosted compose carries a version.

A floating tag (none, ``latest``, a bare major) lets a routine
``docker compose pull`` swap the proxy, the database or the file storage
underneath a customer's installation."""

import re
from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.self-hosted.yml"

# MinIO withdrew its official images (Docker Hub and quay.io, September
# 2026); which image replaces them is decided in HRP-1026. Exact match
# below, so pinning them fails this test until the exemption is removed.
PENDING = {"minio", "minio-init"}


def _pinned(image: str) -> bool:
    if "@sha256:" in image:
        return True
    name = image.rsplit("/", 1)[-1]
    tag = name.split(":", 1)[1] if ":" in name else ""
    return re.search(r"\d+\.\d+|^RELEASE\.", tag) is not None


def test_every_image_is_pinned_to_a_version() -> None:
    if not COMPOSE.exists():
        pytest.skip("self-hosted compose is not part of this tree")
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    unpinned = {
        name
        for name, service in services.items()
        if "image" in service and not _pinned(service["image"])
    }
    assert unpinned == PENDING, f"pin an explicit version tag for: {unpinned}"


@pytest.mark.parametrize(
    ("image", "pinned"),
    [
        ("minio/minio", False),
        ("redis:latest", False),
        ("redis:7-alpine", False),
        ("pgvector/pgvector:pg17", False),
        ("caddy:2.11-alpine", True),
        ("pgvector/pgvector:0.8.7-pg17", True),
        ("registry.local:5000/minio/minio", False),
        ("example.org/storage:RELEASE.2025-09-07T16-13-09Z", True),
    ],
)
def test_pinned(image: str, pinned: bool) -> None:
    assert _pinned(image) is pinned
