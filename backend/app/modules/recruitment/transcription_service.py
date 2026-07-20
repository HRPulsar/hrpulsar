"""Pluggable speech-to-text providers for the interview module.

Two production-ready providers are implemented:

- ``OpenAIWhisperProvider`` — calls the Whisper API via the existing
  OpenAI SDK. The Whisper API itself does not perform speaker
  diarization, so segments share a single speaker label. Whisper has
  a 25 MB request size cap; longer recordings should be routed to
  Deepgram (or pre-split, R4).
- ``DeepgramProvider`` — calls Deepgram ``listen`` API with native
  speaker diarization. Recommended for production interviews.

``AssemblyAIProvider`` and ``FasterWhisperProvider`` are stubs that
raise ``NotImplementedError``. They exist so the ``TranscriptionProvider``
contract is documented and future providers can be added without
churning the interface (see RECRUITING_MODULE.md §8.2).

Tenant routing uses ``TranscriptionProviderConfig.is_active`` as the
selection key. When no row is active the platform default
(``settings.transcription_provider_default``) is used with the
platform-level API key.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.recruitment.models import TranscriptionProviderConfig

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    speaker: str
    start: float
    end: float
    text: str
    confidence: float | None = None


@dataclass
class TranscriptionResult:
    full_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str | None = None
    duration_seconds: float | None = None
    provider: str = ""


class TranscriptionProvider(ABC):
    """Abstract base for speech-to-text providers."""

    provider_name: str = ""

    @abstractmethod
    async def transcribe(
        self,
        audio_url: str,
        *,
        language: str = "ru",
        diarization: bool = True,
    ) -> TranscriptionResult:
        """Transcribe audio referenced by ``audio_url``.

        ``audio_url`` may be a presigned S3 URL or any URL accessible
        from the worker. Implementations decide whether to download the
        bytes locally first (Whisper) or pass the URL directly
        (Deepgram).
        """


# ---------------------------------------------------------------------------
# OpenAI Whisper
# ---------------------------------------------------------------------------


class OpenAIWhisperProvider(TranscriptionProvider):
    provider_name = "whisper"

    # OpenAI Whisper rejects requests larger than 25 MB. We fail fast at
    # this boundary so an oversized recording surfaces a useful error
    # instead of OOM-killing the worker on the audio download.
    WHISPER_MAX_BYTES = 25 * 1024 * 1024

    def __init__(self, api_key: str, model: str = "whisper-1") -> None:
        self._api_key = api_key
        self._model = model

    async def transcribe(
        self,
        audio_url: str,
        *,
        language: str = "ru",
        diarization: bool = True,
    ) -> TranscriptionResult:
        # The Whisper REST endpoint expects a multipart upload with the
        # audio bytes. We stream the presigned URL into a temp file so a
        # half-gig recording cannot pin worker memory; the 25 MB Whisper
        # ceiling is enforced as the bytes arrive.
        import contextlib
        import os
        import tempfile

        async with httpx.AsyncClient(timeout=600) as http:
            with tempfile.NamedTemporaryFile(
                suffix=".audio", delete=False
            ) as tmp:
                tmp_path = tmp.name
                downloaded = 0
                try:
                    async with http.stream("GET", audio_url) as audio_resp:
                        audio_resp.raise_for_status()
                        async for chunk in audio_resp.aiter_bytes(
                            chunk_size=64 * 1024
                        ):
                            downloaded += len(chunk)
                            if downloaded > self.WHISPER_MAX_BYTES:
                                raise ValueError(
                                    "Audio file exceeds Whisper API 25 MB limit; "
                                    "switch to Deepgram or pre-split the recording"
                                )
                            tmp.write(chunk)
                except Exception:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_path)
                    raise

            try:
                with open(tmp_path, "rb") as audio_handle:
                    files = {
                        "file": (
                            "interview.bin",
                            audio_handle,
                            "application/octet-stream",
                        )
                    }
                    data = {
                        "model": self._model,
                        "response_format": "verbose_json",
                        "language": language,
                        "timestamp_granularities[]": "segment",
                    }
                    response = await http.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        data=data,
                        files=files,
                    )
                    response.raise_for_status()
                    body = response.json()
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

        return _whisper_payload_to_result(body, provider=self.provider_name)


def _whisper_payload_to_result(
    body: dict[str, Any], *, provider: str
) -> TranscriptionResult:
    full_text = body.get("text", "") or ""
    raw_segments = body.get("segments") or []
    segments: list[TranscriptSegment] = []
    for seg in raw_segments:
        segments.append(
            TranscriptSegment(
                speaker="speaker_0",
                start=float(seg.get("start") or 0.0),
                end=float(seg.get("end") or 0.0),
                text=str(seg.get("text") or "").strip(),
                confidence=None,
            )
        )
    return TranscriptionResult(
        full_text=full_text.strip(),
        segments=segments,
        language=body.get("language"),
        duration_seconds=body.get("duration"),
        provider=provider,
    )


# ---------------------------------------------------------------------------
# Deepgram
# ---------------------------------------------------------------------------


class DeepgramProvider(TranscriptionProvider):
    provider_name = "deepgram"

    def __init__(self, api_key: str, model: str = "nova-2") -> None:
        self._api_key = api_key
        self._model = model

    async def transcribe(
        self,
        audio_url: str,
        *,
        language: str = "ru",
        diarization: bool = True,
    ) -> TranscriptionResult:
        params: dict[str, Any] = {
            "model": self._model,
            "language": language,
            "punctuate": "true",
            "utterances": "true",
        }
        if diarization:
            params["diarize"] = "true"

        async with httpx.AsyncClient(timeout=600) as http:
            response = await http.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": audio_url},
            )
            response.raise_for_status()
            body = response.json()

        return _deepgram_payload_to_result(body, provider=self.provider_name)


def _deepgram_payload_to_result(
    body: dict[str, Any], *, provider: str
) -> TranscriptionResult:
    results = body.get("results") or {}
    channels = results.get("channels") or []
    duration = (body.get("metadata") or {}).get("duration")
    detected_language = None
    if channels:
        detected_language = (channels[0].get("detected_language") or None)

    utterances = results.get("utterances") or []
    segments: list[TranscriptSegment] = []
    pieces: list[str] = []
    for utt in utterances:
        speaker_idx = utt.get("speaker", 0)
        text = (utt.get("transcript") or "").strip()
        if not text:
            continue
        pieces.append(text)
        segments.append(
            TranscriptSegment(
                speaker=f"speaker_{speaker_idx}",
                start=float(utt.get("start") or 0.0),
                end=float(utt.get("end") or 0.0),
                text=text,
                confidence=utt.get("confidence"),
            )
        )

    full_text = " ".join(pieces).strip()
    if not full_text and channels:
        # Fallback to the channel-level transcript when utterances are
        # missing (e.g. utterances=false on the request).
        alts = (channels[0].get("alternatives") or [{}])[0]
        full_text = (alts.get("transcript") or "").strip()

    return TranscriptionResult(
        full_text=full_text,
        segments=segments,
        language=detected_language,
        duration_seconds=duration,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# Stubs (R4)
# ---------------------------------------------------------------------------


class AssemblyAIProvider(TranscriptionProvider):
    """Placeholder — AssemblyAI integration is planned for Phase R4."""

    provider_name = "assemblyai"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def transcribe(
        self,
        audio_url: str,
        *,
        language: str = "ru",
        diarization: bool = True,
    ) -> TranscriptionResult:
        raise NotImplementedError(
            "AssemblyAI provider is not yet implemented (planned for R4)."
        )


class FasterWhisperProvider(TranscriptionProvider):
    """Placeholder — self-hosted faster-whisper + pyannote, Phase R4."""

    provider_name = "faster_whisper"

    def __init__(self, endpoint: str | None = None) -> None:
        self._endpoint = endpoint

    async def transcribe(
        self,
        audio_url: str,
        *,
        language: str = "ru",
        diarization: bool = True,
    ) -> TranscriptionResult:
        raise NotImplementedError(
            "Self-hosted faster-whisper provider is not yet implemented "
            "(planned for R4)."
        )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


_PROVIDER_REGISTRY: dict[str, type[TranscriptionProvider]] = {
    "whisper": OpenAIWhisperProvider,
    "deepgram": DeepgramProvider,
    "assemblyai": AssemblyAIProvider,
    "faster_whisper": FasterWhisperProvider,
}


def _platform_key_for(provider: str) -> str:
    if provider == "whisper":
        return settings.openai_api_key or ""
    if provider == "deepgram":
        return settings.deepgram_api_key or ""
    if provider == "assemblyai":
        return settings.assemblyai_api_key or ""
    return ""


def _build(provider: str, api_key: str) -> TranscriptionProvider:
    if provider not in _PROVIDER_REGISTRY:
        raise ValueError(f"Unknown transcription provider: {provider}")
    if provider == "whisper":
        return OpenAIWhisperProvider(api_key=api_key)
    if provider == "deepgram":
        return DeepgramProvider(api_key=api_key)
    if provider == "assemblyai":
        return AssemblyAIProvider(api_key=api_key)
    if provider == "faster_whisper":
        return FasterWhisperProvider(endpoint=api_key or None)
    raise ValueError(f"Unknown transcription provider: {provider}")


async def get_transcription_provider(
    db: AsyncSession, tenant_id: uuid.UUID
) -> TranscriptionProvider:
    row = (
        await db.execute(
            select(TranscriptionProviderConfig)
            .where(
                TranscriptionProviderConfig.tenant_id == tenant_id,
                TranscriptionProviderConfig.is_active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if row and row.provider:
        provider = row.provider
        api_key = row.api_key_encrypted or _platform_key_for(provider)
    else:
        provider = settings.transcription_provider_default or "whisper"
        api_key = _platform_key_for(provider)

    return _build(provider, api_key)


def get_transcription_provider_sync(
    db: Session, tenant_id: uuid.UUID
) -> TranscriptionProvider:
    row = (
        db.execute(
            select(TranscriptionProviderConfig)
            .where(
                TranscriptionProviderConfig.tenant_id == tenant_id,
                TranscriptionProviderConfig.is_active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if row and row.provider:
        provider = row.provider
        api_key = row.api_key_encrypted or _platform_key_for(provider)
    else:
        provider = settings.transcription_provider_default or "whisper"
        api_key = _platform_key_for(provider)

    return _build(provider, api_key)


__all__ = [
    "TranscriptionProvider",
    "TranscriptionResult",
    "TranscriptSegment",
    "OpenAIWhisperProvider",
    "DeepgramProvider",
    "AssemblyAIProvider",
    "FasterWhisperProvider",
    "get_transcription_provider",
    "get_transcription_provider_sync",
]
