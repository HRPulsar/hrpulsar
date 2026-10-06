"""Dictating the process by voice (HRP-947): a recording in, its text out.

The visitor records the description on the input page; the text comes back
into the field, where they correct it before sending the check. Nothing is
kept: the recording lives in a temp directory for the length of the request,
removed whatever happens, and the text only travels in the answer.

Guards, cheapest refusal first. The router: the pause, then a per-IP
throttle of its own. Here: a declared body over the ceiling, a reservation
of the longest recording's minutes on today's budget (``RESERVED``, taken
before any work, so parallel recordings cannot all pass one read of the
counter), a sandbox with no transcription provider, then the body itself -
streamed and never read past ``MAX_BODY_BYTES`` - its type, and its length
as ffmpeg decodes it: past ``MAX_SECONDS`` it never reaches a provider.
No captcha: the check the text goes into has one, and a captcha per
recording would ask the visitor twice for one check.

Transcription is the sandbox's chain (``recruitment.transcription_service``):
its own keys if an operator ever configures some, the platform's otherwise,
the language detected by the provider. Every provider refusing, a
transient error of one, or the chain running past ``TRANSCRIBE_TIMEOUT_S``
is a 503 without a retry - the visitor records again. The calls are filed
under ``public_check.transcribe`` against the sandbox (the AI call
context). The reservation is then settled at the minutes the provider
reports - or, when it failed or timed out (it may still have billed), the
minutes measured; a refusal before any provider call gives it all back.
A malformed body is a 415; a visitor gone mid-upload a quiet 400.
"""

from __future__ import annotations

import asyncio
import logging
import math
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from python_multipart.exceptions import MultipartParseError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect, Request

from app.config import settings
from app.core import ai_usage_hooks
from app.core.errors import AppError
from app.modules.public_check import service
from app.modules.recruitment import transcription_service
from app.modules.recruitment.transcription_service import TranscriptionProvider

logger = logging.getLogger(__name__)

# The page's timer stops a recording here; the same number is
# ``VOICE_MAX_SECONDS`` in frontend/src/lib/api/public-check.ts.
MAX_SECONDS = 180
# A recording the page stopped at its timer may run a little past it.
LENGTH_SLACK_S = 5
# Ceiling of measuring one recording; decoding three minutes takes well
# under a second.
MEASURE_TIMEOUT_S = 30
# The whole request body. Three minutes of Opus or AAC at the browsers'
# default bitrate (~128 kbit/s) is ~3 MB; the rest is headroom for a higher
# bitrate. An uncompressed WAV fits about three minutes at 16 kHz mono.
MAX_BODY_BYTES = 10 * 1024 * 1024
FIELD = "audio"
# The containers ``MediaRecorder`` writes - webm (Chromium, Firefox), mp4
# (Safari), ogg (Firefox) - plus WAV and MP3 files. The provider reads the
# format off the file's extension (Whisper refuses an unknown one).
SUFFIXES = {
    "audio/webm": ".webm",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
}
# The daily budget counter (``service.spend_daily``) of transcribed minutes.
MINUTES = "voice_minutes"
# Held on it for every recording before any work: the longest one's minutes.
RESERVED = math.ceil(MAX_SECONDS / 60)
# Ceiling of the whole chain for one recording, seconds. A three-minute
# recording takes a few seconds; a provider hanging past this is the same
# 503 as a refusal. The page gives up a little later
# (``VOICE_TIMEOUT_MS`` in frontend/src/lib/api/public-check.ts).
TRANSCRIBE_TIMEOUT_S = 120
# What the provider calls of a recording are filed under in the AI call
# journal (wave 13's ASR records), against the sandbox. Not a price-list
# code: no credits.
USAGE_ACTION = "public_check.transcribe"


def _too_large() -> AppError:
    return AppError("public_check_voice_too_large", 413)


def _unsupported() -> AppError:
    return AppError("public_check_voice_unsupported", 415)


def _unavailable() -> AppError:
    return AppError("public_check_voice_unavailable", 503)


def _minutes(seconds: float) -> int:
    return max(1, math.ceil(seconds / 60))


async def transcribe(db: AsyncSession, request: Request) -> dict[str, Any]:
    """The text of the recording in the request (``schemas.Transcript``)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    limit = settings.public_check_voice_daily_minutes
    # The "try again tomorrow" 429 once today's minutes cannot hold another
    # recording; fail-closed on an unreachable Redis.
    await service.spend_daily(MINUTES, limit, RESERVED)
    kept = 0  # the minutes the reservation settles at; 0 - none was spent
    try:
        tenant_id, providers = await _chain(db)
        with tempfile.TemporaryDirectory(prefix="hrp-voice-") as workdir:
            path = await _receive(request, Path(workdir))
            measured = await run_in_threadpool(_measure, path)
            # From here a provider is called: it may bill a failed call too.
            kept = _minutes(measured)
            try:
                # No check exists yet: one recording is one unit of work.
                with ai_usage_hooks.call_context(
                    tenant_id=tenant_id,
                    action=USAGE_ACTION,
                    work_unit_id=uuid.uuid4(),
                ):
                    result, error = await asyncio.wait_for(
                        transcription_service.transcribe_with_chain(
                            providers, path, language=None
                        ),
                        TRANSCRIBE_TIMEOUT_S,
                    )
            except Exception as exc:  # noqa: BLE001 - 429/5xx/timeouts of a provider
                logger.warning("public check: transcription failed", exc_info=True)
                raise _unavailable() from exc
        if result is None:
            logger.warning(
                "public check: no provider transcribed a recording: %s", error
            )
            raise _unavailable()
        seconds = result.duration_seconds or (
            result.segments[-1].end if result.segments else None
        )
        kept = _minutes(seconds or measured)
        return {"text": result.full_text.strip(), "language": result.language}
    finally:
        if limit > 0:
            await service.adjust_daily(MINUTES, kept - RESERVED)


def _measure(path: str) -> float:
    """The recording's length in seconds, as ffmpeg decodes it - not what
    the container's header claims (a browser's webm names none). Over
    ``MAX_SECONDS`` is ``public_check_voice_too_long``, unreadable a 415;
    no ffmpeg is the 503 of a service that cannot cap what it sends.

    ponytail: the length is the decoded stream's last timestamp; a crafted
    file with lying timestamps passes it, its cost still bounded by
    ``MAX_BODY_BYTES`` and settled at the provider's reported length."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-nostats",
                "-progress",
                "pipe:1",
                "-i",
                path,
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=MEASURE_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:
        logger.error("public check: no ffmpeg to measure a recording")
        raise _unavailable() from exc
    except subprocess.TimeoutExpired as exc:
        raise _unsupported() from exc
    times = [
        line.partition("=")[2]
        for line in proc.stdout.splitlines()
        if line.startswith("out_time_us=")
    ]
    if proc.returncode != 0 or not times or not times[-1].isdigit():
        raise _unsupported()
    seconds = int(times[-1]) / 1_000_000
    if seconds > MAX_SECONDS + LENGTH_SLACK_S:
        raise AppError("public_check_voice_too_long", 413)
    return seconds


async def _chain(
    db: AsyncSession,
) -> tuple[uuid.UUID, list[TranscriptionProvider]]:
    """The sandbox and its transcription providers, in the order they are tried.
    Committed before any provider is called: no transaction stays open
    across a network call (and a sandbox created here is kept)."""
    tenant_id, _ = await service.ensure_sandbox(db)
    providers = await db.run_sync(
        lambda session: transcription_service.get_transcription_chain_sync(
            session, tenant_id
        )
    )
    await db.commit()
    if not providers:
        logger.error("public check: no transcription provider for dictation")
        raise _unavailable()
    return tenant_id, providers


async def _bounded(request: Request) -> AsyncGenerator[bytes, None]:
    """The request body, refused with 413 the moment it passes the ceiling -
    a missing or lying Content-Length included."""
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_BODY_BYTES:
            raise _too_large()
        yield chunk


async def _receive(request: Request, workdir: Path) -> str:
    """The ``audio`` part of the multipart body, written to ``workdir`` with
    the extension of its type. Returns the file's path."""
    if (
        not request.headers.get("content-type", "")
        .lower()
        .startswith("multipart/form-data")
    ):
        raise _unsupported()
    parser = MultiPartParser(
        request.headers, _bounded(request), max_files=1, max_fields=0
    )
    try:
        form = await parser.parse()
    except (MultiPartException, MultipartParseError) as exc:
        raise _unsupported() from exc
    except ClientDisconnect as exc:
        # The visitor went away mid-upload: nobody reads the answer, and it
        # is no server error worth a traceback.
        logger.info("public check: recording upload cut off by the client")
        raise AppError("public_check_voice_incomplete", 400) from exc
    try:
        audio = form.get(FIELD)
        if not isinstance(audio, UploadFile):
            raise _unsupported()
        kind = (audio.content_type or "").split(";")[0].strip().lower()
        suffix = SUFFIXES.get(kind)
        if suffix is None:
            raise _unsupported()
        path = workdir / f"recording{suffix}"
        with path.open("wb") as out:
            await run_in_threadpool(shutil.copyfileobj, audio.file, out)
        return str(path)
    finally:
        await form.close()
