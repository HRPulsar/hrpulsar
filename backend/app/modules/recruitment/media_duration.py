"""Best-effort audio duration probing.

The recruitment module uses ``Interview.duration_seconds`` for two
purposes:

- The Whisper / Deepgram pipeline writes the value it gets back from the
  STT provider after transcription has succeeded
  (``transcription_service.py`` → ``tasks.transcribe_interview_task``).
- Per-minute billing for ``recruitment.transcribe_interview_min`` needs
  to know the duration *before* the STT call is queued so the credit
  precheck reflects the actual cost.

This module fills the second hole. We probe the audio container with
``mutagen`` (pure Python — no system binary needed) once the multipart
upload finalises in ``interview_service.complete_interview_upload`` and
persist the result on the row. Failures are swallowed so a probe-time
hiccup never blocks the upload; per-minute billing falls back to the
minimum charge declared in ``_transcribe_cost`` when ``duration_seconds``
is still ``None``.
"""

from __future__ import annotations

import logging
import os
from typing import IO

log = logging.getLogger(__name__)


def get_audio_duration_seconds(source: str | bytes | IO[bytes]) -> float | None:
    """Return the audio/video duration in seconds, or ``None`` on failure.

    ``source`` may be a filesystem path, raw bytes, or any file-like
    object that ``mutagen.File`` accepts. Mutagen handles common
    containers (MP3, MP4/M4A, FLAC, OGG, WAV) without external system
    binaries which keeps the SaaS Docker image lean.
    """

    try:
        import mutagen

        if isinstance(source, bytes):
            import io

            handle: IO[bytes] = io.BytesIO(source)
            audio = mutagen.File(handle)
        else:
            audio = mutagen.File(source)
        if audio is None or audio.info is None:
            return None
        length = getattr(audio.info, "length", None)
        if length is None:
            return None
        return float(length)
    except Exception:  # noqa: BLE001 — best-effort, never break the caller
        log.debug("media_duration: probe failed", exc_info=True)
        return None


def probe_s3_audio_duration(key: str) -> float | None:
    """Download an S3 object to a temp file and probe its duration.

    Returns ``None`` if S3 is not configured or the probe fails. Used by
    ``interview_service.complete_interview_upload`` immediately after the
    multipart upload commits so per-minute billing has the value when
    the recruiter clicks "Transcribe".
    """

    try:
        from app.config import settings
        from app.core.s3 import get_s3_client

        client = get_s3_client()
        if client is None:
            return None

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            client.download_file(settings.s3_bucket, key, tmp_path)
            return get_audio_duration_seconds(tmp_path)
        finally:
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
    except Exception:  # noqa: BLE001
        log.debug("media_duration: S3 probe failed for %s", key, exc_info=True)
        return None
