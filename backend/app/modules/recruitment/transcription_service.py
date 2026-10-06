"""Pluggable speech-to-text providers for the interview module.

Four providers are implemented:

- ``DeepgramProvider`` — the ``listen`` API with native speaker
  diarization, in one request.
- ``OpenAIWhisperProvider`` — the Whisper API. It does not diarize at
  all, so the transcript comes back single-voiced and the worker
  recovers the roles with an LLM pass (``speaker_roles``). Whisper also
  caps a request at 25 MB; a recording above it is split into chunks and
  stitched back together (HRP-646). A tenant row may point it at its own
  OpenAI-compatible server (``settings["base_url"]``, HRP-985).
- ``AssemblyAIProvider`` — upload, then a polled transcript job, with
  native diarization.
- ``YandexSpeechKitProvider`` — v3 asynchronous file recognition with
  speaker labeling, for deployments that cannot send audio abroad.

Every credential a workspace has joins one chain (see
``get_transcription_chain_sync``), so a dead key costs a provider, not
the interview. A recording is only ever chunked for a provider that
declares ``max_request_bytes`` — the diarizing ones number speakers per
request, and splitting would rename them halfway through. Every attempt
in the chain is one row of the AI call log (HRP-970).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai_usage_hooks, url_guard
from app.core.errors import AppError
from app.modules.ai.providers import decrypt_row_key
from app.modules.recruitment.media_prep import split_audio
from app.modules.recruitment.models import TranscriptionProviderConfig

logger = logging.getLogger(__name__)

# Provider answers that mean "this credential will never work": a dead or
# deactivated key, a suspended account, an exhausted plan.
_PROVIDER_REFUSALS = frozenset({401, 402, 403})


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
    # The model that actually ran, when the provider reports it (AssemblyAI
    # routes between models); the AI call log falls back to the provider's.
    model: str | None = None


class TranscriptionProvider(ABC):
    """Abstract base for speech-to-text providers."""

    provider_name: str = ""
    # For the AI call log (HRP-970): the provider's model, and whose key
    # the call runs on — platform | byok | local, set by the chain builder.
    model: str = ""
    credential_source: str = "platform"

    # Hard request-size ceiling of the provider's API, if it has one.
    # A recording above it is split into chunks by the chain (HRP-646);
    # a provider without a ceiling always gets the file whole.
    max_request_bytes: int | None = None

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        diarization: bool = True,
    ) -> TranscriptionResult:
        """Transcribe the local media file at ``audio_path``.

        The worker materializes the recording on its own disk — and, where
        ffmpeg is available, re-encodes it to mono 16 kHz audio — before
        the chain runs, so a provider only ever opens a file. Storage never
        has to be reachable from the provider's network (HRP-385
        follow-up), and no half-gig video is pushed through their API.

        ``language`` is an ISO-639-1 code, or ``None`` to let the
        provider detect it — the interview is whatever language it was
        conducted in, and hardcoding one transcribes the rest as
        gibberish.
        """


def _media_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


class _SpeakerNumbering:
    """Provider speaker labels ("A", "1", "spk_2") → our ``speaker_N``.

    Numbered by order of appearance, so the first voice on the recording
    is speaker_0 whatever the provider chose to call it, and the segment
    rows keep the shape the UI and the analysis prompt already expect.
    """

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def label(self, raw: Any) -> str:
        key = str(raw) if raw is not None else ""
        if key not in self._seen:
            self._seen[key] = len(self._seen)
        return f"speaker_{self._seen[key]}"


async def _file_bytes(path: str) -> AsyncIterator[bytes]:
    """Stream a local file into a request body.

    httpx refuses a plain file object as ``content`` on an async client,
    and reading the whole recording into memory is what OOM-killed the
    worker before.
    """

    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            yield chunk


# ---------------------------------------------------------------------------
# OpenAI Whisper
# ---------------------------------------------------------------------------


OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIWhisperProvider(TranscriptionProvider):
    provider_name = "whisper"

    # OpenAI Whisper rejects requests larger than 25 MB. Declared as the
    # provider's own property so the chain can split the recording for it
    # instead of writing the interview off.
    max_request_bytes = 25 * 1024 * 1024

    def __init__(
        self, api_key: str, model: str = "whisper-1", base_url: str | None = None
    ) -> None:
        self._api_key = api_key
        self.model = model
        # HRP-985: a tenant's own OpenAI-compatible server. Only ever set
        # off the platform key — see ``_build``.
        self._base_url = base_url

    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        diarization: bool = True,
    ) -> TranscriptionResult:
        size = os.path.getsize(audio_path)
        if size > self.max_request_bytes:
            raise ValueError(
                "Audio file exceeds Whisper API 25 MB limit; "
                "switch to Deepgram or pre-split the recording"
            )

        # The Whisper REST endpoint expects a multipart upload. The
        # filename travels with it on purpose: OpenAI reads the container
        # format off the extension, so "interview.bin" is rejected as an
        # unknown format.
        with open(audio_path, "rb") as audio_handle:
            files = {
                "file": (
                    os.path.basename(audio_path),
                    audio_handle,
                    _media_type(audio_path),
                )
            }
            data = {
                "model": self.model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
            # Omitted entirely when unknown: Whisper detects the
            # language itself, and a wrong hint is worse than none.
            if language:
                data["language"] = language
            base_url = (self._base_url or OPENAI_BASE_URL).rstrip("/")
            # HRP-985: a tenant-set address goes through the same SSRF
            # layer as an LLM base_url — on saas it is re-resolved, checked
            # and pinned on every request; None elsewhere (onprem, OpenAI).
            client = (
                url_guard.tenant_endpoint_http_client(
                    base_url,
                    error_code="llm_base_url_not_public",
                    timeout=httpx.Timeout(600.0, connect=30.0),
                )
                if self._base_url
                else None
            ) or httpx.AsyncClient(timeout=600)
            # A local server may run without auth.
            headers = (
                {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
            )
            async with (
                client as http,
                http.stream(
                    "POST",
                    f"{base_url}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files,
                ) as response,
            ):
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw += chunk
                    if len(raw) > _WHISPER_MAX_RESPONSE_BYTES:
                        raise ValueError("Whisper response exceeds 20 MB")
        # A ValueError moves the chain on: a server answering garbage will
        # answer it again, so a retry would only replay the upload.
        try:
            body = json.loads(raw)
        except ValueError:
            raise ValueError("Whisper response is not JSON") from None
        if not isinstance(body, dict):
            raise ValueError("Whisper response is not a JSON object")

        return _whisper_payload_to_result(body, provider=self.provider_name)


# A verbose_json transcript of a 25 MB upload is a few MB; the cap keeps a
# misbehaving tenant server from filling the worker's memory (review B4).
_WHISPER_MAX_RESPONSE_BYTES = 20 * 1024 * 1024


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
        self.model = model

    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        diarization: bool = True,
    ) -> TranscriptionResult:
        params: dict[str, Any] = {
            "model": self.model,
            "punctuate": "true",
            "utterances": "true",
        }
        if language:
            params["language"] = language
        else:
            params["detect_language"] = "true"
        if diarization:
            params["diarize"] = "true"

        # The worker streams the media into the request instead of handing
        # Deepgram a presigned URL to fetch: their side never learns the
        # storage host, the bucket does not have to be reachable from the
        # public internet, and in a proxied deployment the audio rides the
        # same egress channel as the rest of the AI traffic.
        async with httpx.AsyncClient(timeout=600) as http:
            response = await http.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": _media_type(audio_path),
                },
                content=_file_bytes(audio_path),
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
    """AssemblyAI ``/v2/transcript`` with native speaker diarization.

    Three legs instead of one call: the recording is uploaded, a
    transcript job is created against the upload, and the job is polled
    until it finishes. The upload endpoint is what keeps the promise made
    in HRP-644 — the worker sends bytes, and no storage URL of ours is
    handed to a third party.
    """

    provider_name = "assemblyai"
    # No model is requested: AssemblyAI routes between its own (Universal-3.5
    # Pro first) and reports the one that ran in ``speech_model_used``.
    model = "universal-3-5-pro"

    _BASE_URL = "https://api.assemblyai.com/v2"

    # Without a hint AssemblyAI returns a Russian interview as one voice
    # and one hour-long utterance — measured, not assumed. Telling it how
    # many people are in the room turns diarization on and breaks the
    # transcript into turns. Two is what a one-on-one interview has;
    # a panel is configured per provider row.
    _SPEAKERS_EXPECTED = 2
    # An hour of audio is minutes of work on their side; polling is cheap
    # and the worker has nothing else to do meanwhile.
    _POLL_INTERVAL_SECONDS = 5.0
    _POLL_TIMEOUT_SECONDS = 1800.0

    def __init__(self, api_key: str, speakers_expected: int = 0) -> None:
        self._api_key = api_key
        self._speakers_expected = speakers_expected or self._SPEAKERS_EXPECTED

    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        diarization: bool = True,
    ) -> TranscriptionResult:
        headers = {"authorization": self._api_key}
        payload: dict[str, Any] = {"speaker_labels": diarization}
        if diarization:
            payload["speakers_expected"] = self._speakers_expected
        if language:
            payload["language_code"] = language
        else:
            payload["language_detection"] = True

        async with httpx.AsyncClient(timeout=600) as http:
            uploaded = await http.post(
                f"{self._BASE_URL}/upload",
                headers=headers,
                content=_file_bytes(audio_path),
            )
            uploaded.raise_for_status()
            payload["audio_url"] = uploaded.json()["upload_url"]

            created = await http.post(
                f"{self._BASE_URL}/transcript", headers=headers, json=payload
            )
            created.raise_for_status()
            transcript_id = created.json()["id"]

            deadline = time.monotonic() + self._POLL_TIMEOUT_SECONDS
            while True:
                polled = await http.get(
                    f"{self._BASE_URL}/transcript/{transcript_id}", headers=headers
                )
                polled.raise_for_status()
                body = polled.json()
                status = body.get("status")
                if status == "completed":
                    break
                if status == "error":
                    raise ValueError(
                        f"AssemblyAI could not transcribe the recording: "
                        f"{body.get('error') or 'unknown error'}"
                    )
                if time.monotonic() > deadline:
                    raise ValueError(
                        "AssemblyAI did not finish the transcript within "
                        f"{int(self._POLL_TIMEOUT_SECONDS / 60)} minutes"
                    )
                await asyncio.sleep(self._POLL_INTERVAL_SECONDS)

        return _assemblyai_payload_to_result(body, provider=self.provider_name)


def _assemblyai_payload_to_result(
    body: dict[str, Any], *, provider: str
) -> TranscriptionResult:
    utterances = body.get("utterances") or []
    segments: list[TranscriptSegment] = []
    speakers = _SpeakerNumbering()
    for utt in utterances:
        text = (utt.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                # Their labels are letters (A, B, C); ours are the
                # speaker_N the rest of the module and the UI speak.
                speaker=speakers.label(utt.get("speaker")),
                start=float(utt.get("start") or 0) / 1000.0,
                end=float(utt.get("end") or 0) / 1000.0,
                text=text,
                confidence=utt.get("confidence"),
            )
        )

    full_text = " ".join(seg.text for seg in segments).strip()
    if not full_text:
        full_text = (body.get("text") or "").strip()

    return TranscriptionResult(
        full_text=full_text,
        segments=segments,
        language=body.get("language_code"),
        duration_seconds=body.get("audio_duration"),
        provider=provider,
        model=body.get("speech_model_used"),
    )


class YandexSpeechKitProvider(TranscriptionProvider):
    """Yandex SpeechKit v3 asynchronous file recognition with diarization.

    Speaker labeling there is narrower than Deepgram's: it needs the
    ``FULL_DATA`` processing mode, a mono recording, and it distinguishes
    at most two voices. That is exactly a one-on-one interview — which is
    what this module transcribes — and the ffmpeg pass upstream already
    hands it mono audio. A panel interview will come back with the two
    loudest speakers merged into the rest.
    """

    provider_name = "yandex_speechkit"

    _SUBMIT_URL = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
    _RESULT_URL = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"
    _OPERATION_URL = "https://operation.api.cloud.yandex.net/operations/"
    _POLL_INTERVAL_SECONDS = 5.0
    _POLL_TIMEOUT_SECONDS = 1800.0

    # The v3 file API takes the audio inline as base64 in the JSON body —
    # there is no multipart upload — so the recording sits in worker
    # memory while the request is built. Fine for the mono 16 kHz audio
    # ffmpeg produces (~14 MB an hour), refused for anything larger so a
    # raw 500 MB video cannot OOM the worker.
    _MAX_INLINE_BYTES = 100 * 1024 * 1024

    # SpeechKit names the container explicitly; ours follows whatever
    # ffmpeg produced (opus), or the untouched original when it could not.
    _CONTAINERS = {
        ".ogg": "OGG_OPUS",
        ".oga": "OGG_OPUS",
        ".mp3": "MP3",
        ".wav": "WAV",
    }

    # SpeechKit wants a locale, not an ISO-639-1 code. Anything not listed
    # goes without a language restriction — auto-detection beats sending a
    # locale their models do not know.
    _LOCALES = {"ru": "ru-RU", "en": "en-US", "kk": "kk-KZ", "uz": "uz-UZ"}

    def __init__(
        self, api_key: str, folder_id: str = "", model: str = "general"
    ) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        # ``general`` is the only model that changes anything today:
        # general:rc and deferred-general returned identical text on a real
        # interview, and "premium" does not exist in v3. Configurable so a
        # new SpeechKit model can be tried without a release.
        self.model = model

    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        diarization: bool = True,
    ) -> TranscriptionResult:
        if not self._folder_id:
            raise ValueError(
                "Yandex SpeechKit needs a folder id alongside the API key"
            )
        size = os.path.getsize(audio_path)
        if size > self._MAX_INLINE_BYTES:
            raise ValueError(
                "Recording is too large for the Yandex SpeechKit inline upload"
            )

        container = self._CONTAINERS.get(
            os.path.splitext(audio_path)[1].lower(), "MP3"
        )
        model: dict[str, Any] = {
            "model": self.model,
            "audioFormat": {"containerAudio": {"containerAudioType": container}},
            "textNormalization": {
                "textNormalization": "TEXT_NORMALIZATION_ENABLED",
                "literatureText": True,
            },
            # Diarization is only computed over the whole recording.
            "audioProcessingType": "FULL_DATA",
        }
        locale = self._LOCALES.get(language or "")
        if locale:
            model["languageRestriction"] = {
                "restrictionType": "WHITELIST",
                "languageCode": [locale],
            }
        body: dict[str, Any] = {
            "content": base64.b64encode(
                await asyncio.to_thread(_read_file, audio_path)
            ).decode(),
            "recognitionModel": model,
        }
        if diarization:
            body["speakerLabeling"] = {
                "speakerLabeling": "SPEAKER_LABELING_ENABLED"
            }

        headers = {
            "Authorization": f"Api-Key {self._api_key}",
            "x-folder-id": self._folder_id,
        }
        async with httpx.AsyncClient(timeout=600) as http:
            submitted = await http.post(self._SUBMIT_URL, headers=headers, json=body)
            submitted.raise_for_status()
            operation_id = submitted.json()["id"]

            deadline = time.monotonic() + self._POLL_TIMEOUT_SECONDS
            while True:
                operation = await http.get(
                    f"{self._OPERATION_URL}{operation_id}", headers=headers
                )
                operation.raise_for_status()
                state = operation.json()
                if state.get("done"):
                    if state.get("error"):
                        raise ValueError(
                            "Yandex SpeechKit could not transcribe the recording: "
                            f"{state['error'].get('message') or 'unknown error'}"
                        )
                    break
                if time.monotonic() > deadline:
                    raise ValueError(
                        "Yandex SpeechKit did not finish the transcript within "
                        f"{int(self._POLL_TIMEOUT_SECONDS / 60)} minutes"
                    )
                await asyncio.sleep(self._POLL_INTERVAL_SECONDS)

            recognized = await http.get(
                self._RESULT_URL,
                params={"operationId": operation_id},
                headers=headers,
            )
            recognized.raise_for_status()
            raw = recognized.text

        return _yandex_payload_to_result(raw, provider=self.provider_name)


def _read_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _yandex_payload_to_result(raw: str, *, provider: str) -> TranscriptionResult:
    """Parse the newline-delimited JSON stream ``getRecognition`` returns.

    Three things about that stream are worth knowing, all of them learned
    from a real recognition rather than the reference:

    - There is no ``speakerTag`` anywhere. With speaker labeling on,
      SpeechKit gives each voice its own ``channelTag`` and its own
      ``finalIndex`` sequence — that tag *is* the diarization. A recording
      it did not separate comes back on one tag, single-voiced, and the
      worker's LLM role pass takes over from there.
    - ``alternatives[].startTimeMs`` is not when the speech starts, it is
      where the previous final of that channel ended — silence included.
      The real span lives in ``words``; taking the alternative's own
      figure put a candidate's answer at 00:00.
    - Each ``final`` is followed by a ``finalRefinement`` carrying the same
      span with punctuation and capitals. Keyed by (channel, finalIndex),
      the refinement replaces the raw text instead of doubling it.
    """

    chunks: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        result = payload.get("result") or {}
        cursors = result.get("audioCursors") or {}
        channel = str(result.get("channelTag") or "")

        final = result.get("final")
        refinement = result.get("finalRefinement") or {}
        if final:
            index = str(cursors.get("finalIndex") or len(order))
            alternative = (final.get("alternatives") or [{}])[0]
        elif refinement:
            index = str(refinement.get("finalIndex") or "")
            alternative = (
                (refinement.get("normalizedText") or {}).get("alternatives") or [{}]
            )[0]
        else:
            # partial / eouUpdate — progress, not transcript.
            continue

        text = (alternative.get("text") or "").strip()
        if not text:
            continue
        words = alternative.get("words") or []
        start = _ms_to_seconds(
            words[0].get("startTimeMs") if words else alternative.get("startTimeMs")
        )
        end = _ms_to_seconds(
            words[-1].get("endTimeMs") if words else alternative.get("endTimeMs")
        )

        key = (channel, index)
        if key not in chunks:
            order.append(key)
            chunks[key] = {"channel": channel, "start": start, "end": end}
        chunks[key]["text"] = text

    speakers = _SpeakerNumbering()
    segments = [
        TranscriptSegment(
            speaker=speakers.label(chunks[key]["channel"]),
            start=chunks[key]["start"],
            end=chunks[key]["end"],
            text=chunks[key]["text"],
        )
        # Back into chronological order: the channels are interleaved, so
        # the stream order is per voice, not per recording.
        for key in sorted(order, key=lambda k: chunks[k]["start"])
        if chunks[key].get("text")
    ]

    return TranscriptionResult(
        full_text=" ".join(seg.text for seg in segments).strip(),
        segments=segments,
        language=None,
        duration_seconds=max((seg.end for seg in segments), default=None),
        provider=provider,
    )


def _ms_to_seconds(value: Any) -> float:
    # SpeechKit returns int64 fields as strings.
    try:
        return float(value or 0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


# The order the chain tries configured credentials in (HRP-646), set by
# measuring all four against the same Russian interview.
#
# Lost speakers we can recover, lost words we cannot — that is what ranks
# them. The LLM role pass turns a single-voiced transcript back into
# interviewer and candidate, but nothing turns a garbled transliteration
# back into "e-commerce", and a term the model never sees is a competence
# the analysis never scores.
#
# AssemblyAI first: the only one that got both right, terms and speakers
# (the latter needs `speakers_expected` — see the provider). Deepgram
# second on the strength of its text alone: its diarizer returned one
# speaker for every model, bitrate and length we tried, so the role pass
# does that part. SpeechKit third — it diarizes properly but mangles the
# anglicisms an IT interview is full of; it is also the only one that
# keeps audio inside Russia, and on that deployment it is the only key
# configured anyway. Whisper last: no diarization, no punctuation, and a
# 25 MB ceiling that costs a chunking pass — but the OpenAI key is the
# one nearly every workspace already has, which is exactly what a last
# resort should be.
#
# A tenant's own key always outranks a platform one, whatever the provider.
_CHAIN_ORDER = ("assemblyai", "deepgram", "yandex_speechkit", "whisper")

# HRP-1005: the company each chain entry hands audio to.
_CHAIN_PROCESSOR = {
    "assemblyai": "assemblyai",
    "deepgram": "deepgram",
    "yandex_speechkit": "yandex",
    "whisper": "openai",
}


def _platform_key_for(provider: str) -> str:
    if provider == "whisper":
        return settings.openai_api_key or ""
    if provider == "deepgram":
        return settings.deepgram_api_key or ""
    if provider == "assemblyai":
        return settings.assemblyai_api_key or ""
    if provider == "yandex_speechkit":
        # A dedicated SpeechKit key when there is one; the YandexGPT
        # service account otherwise, which is the same cloud and often the
        # same key with one more role on it.
        return settings.yandex_speechkit_api_key or settings.yandex_api_key or ""
    return ""


def _build(
    provider: str,
    api_key: str,
    config: dict | None = None,
    *,
    source: str = "platform",
) -> TranscriptionProvider:
    config = config or {}
    built: TranscriptionProvider
    if provider == "whisper":
        # A platform key never travels to a tenant-set address: the
        # platform's Whisper is always OpenAI (HRP-985).
        base_url = str(config.get("base_url") or "").strip()
        built = OpenAIWhisperProvider(
            api_key=api_key,
            base_url=base_url if base_url and source != "platform" else None,
        )
    elif provider == "deepgram":
        built = DeepgramProvider(api_key=api_key)
    elif provider == "assemblyai":
        built = AssemblyAIProvider(
            api_key=api_key,
            speakers_expected=int(config.get("speakers_expected") or 0),
        )
    elif provider == "yandex_speechkit":
        # SpeechKit addresses the account by folder, so the key alone is
        # not a credential: the tenant's row carries its own folder id,
        # and the platform folder is the fallback.
        built = YandexSpeechKitProvider(
            api_key=api_key,
            folder_id=str(config.get("folder_id") or "")
            or (settings.yandex_folder_id or ""),
            model=str(config.get("model") or "general"),
        )
    else:
        raise ValueError(f"Unknown transcription provider: {provider}")
    built.credential_source = source
    return built


def _platform_order() -> tuple[str, ...]:
    """``_CHAIN_ORDER`` with ``TRANSCRIPTION_PROVIDER_DEFAULT`` moved first.

    Empty keeps the measured order (HRP-1007); config validation has
    already refused an unknown name at startup.
    """
    first = settings.transcription_provider_default
    if first not in _CHAIN_ORDER:
        return _CHAIN_ORDER
    return (first, *(name for name in _CHAIN_ORDER if name != first))


def get_transcription_chain_sync(
    db: Session, tenant_id: uuid.UUID
) -> list[TranscriptionProvider]:
    """Every credential the workspace has, in the order they are tried.

    One dead credential used to take the whole feature down with it: the
    task resolved a single provider and a 401 from it was simply the end
    (2026-08 Deepgram account deactivation). The chain is the fallback —
    the caller walks it and only gives up when every provider has refused.

    The tenant's own credentials come first, in ``_CHAIN_ORDER``. Then
    everything that runs on a platform key — a row without its own key and
    the providers the tenant has not configured alike — with
    ``TRANSCRIPTION_PROVIDER_DEFAULT`` first and the rest in
    ``_CHAIN_ORDER`` (HRP-1007). Providers that are not implemented are
    never built: their rows are not in ``_CHAIN_ORDER``.

    A tenant running its own Whisper server gets no platform tail: its
    audio does not leave its server unless the Whisper row says
    ``allow_platform_fallback`` (off by default).
    """

    rows = list(
        db.execute(
            select(TranscriptionProviderConfig).where(
                TranscriptionProviderConfig.tenant_id == tenant_id,
                TranscriptionProviderConfig.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    by_provider = {row.provider: row for row in rows if row.provider}

    from app.modules.ai import processors

    allowed = processors.allowed_processors_sync(db, tenant_id)

    chain: list[TranscriptionProvider] = []
    own: set[str] = set()
    platform_fallback = True
    for name in _CHAIN_ORDER:
        row = by_provider.get(name)
        if row is None:
            continue
        own_key = decrypt_row_key(row, kind="transcription_provider")
        if own_key:
            # BYOK is never restricted by the processor list (HRP-1005 R4).
            chain.append(_build(name, own_key, row.settings, source="byok"))
            own.add(name)
        elif (
            name == "whisper"
            and str((row.settings or {}).get("base_url") or "").strip()
        ):
            # The tenant's own OpenAI-compatible server without auth: its
            # audio stays there, never on the platform key (HRP-985).
            chain.append(_build(name, "", row.settings, source="local"))
            own.add(name)
            # Review B3: nor on any other platform key - unless the tenant
            # opted in on this row (``allow_platform_fallback``).
            platform_fallback = bool(
                (row.settings or {}).get("allow_platform_fallback")
            )

    if not platform_fallback:
        return chain
    for name in _platform_order():
        platform_key = _platform_key_for(name)
        # HRP-1005: a platform key reaches only the processors the tenant
        # may use — a keyless row (F1 review) and the fallback alike.
        if name in own or not platform_key or _CHAIN_PROCESSOR[name] not in allowed:
            continue
        row = by_provider.get(name)
        # A keyless row keeps its own settings (speakers_expected, folder).
        chain.append(
            _build(name, platform_key, row.settings if row else None, source="platform")
        )
    return chain


def merge_chunk_results(
    chunks: list[tuple[TranscriptionResult, float]],
) -> TranscriptionResult:
    """Stitch per-chunk results back onto the recording's own clock.

    Every chunk is transcribed as if it started at zero, so its timecodes
    are shifted by the chunk's offset. Chunks overlap on purpose — a
    sentence cut in half is transcribed whole by one side of the seam —
    and the duplicate is dropped here.

    A segment is dropped when its *midpoint* is inside what we already
    have, not merely its start: at the seam one segment always straddles
    the boundary, and dropping it for starting early swallowed a whole
    sentence of the interview. Half a sentence said twice reads as a
    stutter; half a sentence missing is evidence the analysis never sees.
    """

    segments: list[TranscriptSegment] = []
    for result, offset in chunks:
        for seg in result.segments:
            start, end = seg.start + offset, seg.end + offset
            if segments and (start + end) / 2 < segments[-1].end:
                continue
            segments.append(
                TranscriptSegment(
                    speaker=seg.speaker,
                    start=start,
                    end=end,
                    text=seg.text,
                    confidence=seg.confidence,
                )
            )

    full_text = " ".join(seg.text for seg in segments if seg.text).strip()
    if not full_text:
        # A provider that returned text but no segments (or nothing at
        # all): keep whatever words came back rather than an empty
        # transcript.
        full_text = " ".join(r.full_text for r, _ in chunks if r.full_text).strip()

    return TranscriptionResult(
        full_text=full_text,
        segments=segments,
        language=next((r.language for r, _ in chunks if r.language), None),
        duration_seconds=segments[-1].end if segments else None,
        provider=chunks[0][0].provider if chunks else "",
    )


async def _transcribe_chunks(
    provider: TranscriptionProvider,
    chunks: list[tuple[str, float]],
    *,
    language: str | None,
) -> TranscriptionResult:
    """Transcribe chunk by chunk, then merge.

    Sequential on purpose: the chunks are one recording and the provider's
    rate limit is shared between them, so firing them at once buys nothing.
    Diarization is off — only providers with a request-size ceiling are
    ever chunked, and those do not diarize anyway; one that does (Deepgram)
    numbers speakers per request, which would make ``speaker_0`` of the
    second chunk a different person.
    """

    results: list[tuple[TranscriptionResult, float]] = []
    for path, offset in chunks:
        results.append(
            (
                await provider.transcribe(path, language=language, diarization=False),
                offset,
            )
        )
    return merge_chunk_results(results)


async def _run_provider(
    provider: TranscriptionProvider,
    audio_path: str,
    *,
    language: str | None,
) -> TranscriptionResult | None:
    """One provider's turn, splitting the recording if its API needs it.

    ``None`` means this provider cannot take this file at all — it has a
    request-size ceiling and the recording could not be split (no ffmpeg,
    or a container it refused). The caller moves on to the next provider,
    exactly as it does for a refused credential.
    """

    limit = provider.max_request_bytes
    if not limit or _file_size(audio_path) <= limit:
        return await provider.transcribe(
            audio_path, language=language, diarization=True
        )

    with tempfile.TemporaryDirectory(prefix="hrp-transcribe-") as workdir:
        chunks = split_audio(audio_path, workdir, max_bytes=limit)
        if not chunks:
            return None
        logger.info(
            "Split the recording into %s chunks for %s",
            len(chunks),
            provider.provider_name,
        )
        return await _transcribe_chunks(provider, chunks, language=language)


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


async def _journal(
    provider: TranscriptionProvider,
    started: float,
    *,
    result: TranscriptionResult | None = None,
    error_code: str | None = None,
) -> None:
    """One provider attempt -> one row of the AI call log (HRP-970).

    Attribution is whatever call context the caller bound (the interview
    task binds the interview); a call outside any context lands
    unattributed. ``getattr``: the chain also takes duck-typed providers.
    """
    model = (result.model if result else None) or getattr(provider, "model", "")
    record = ai_usage_hooks.CallRecord(
        kind="transcription",
        provider=provider.provider_name,
        model=model or "",
        credential_source=getattr(provider, "credential_source", "platform"),
        latency_ms=int((time.perf_counter() - started) * 1000),
        status="error" if error_code else "ok",
        error_code=error_code,
        audio_seconds=result.duration_seconds if result else None,
    )
    try:
        await ai_usage_hooks.record_call(record)
    except Exception:  # noqa: BLE001 — the journal must never break a call
        logger.exception("AI usage record failed (transcription)")


async def transcribe_with_chain(
    providers: list[TranscriptionProvider],
    audio_path: str,
    *,
    language: str | None = None,
) -> tuple[TranscriptionResult | None, str]:
    """Walk the chain until one provider transcribes the recording.

    Returns ``(result, last_error)`` — ``result`` is ``None`` only when
    every provider refused. A refusal is a credential or quota answer
    (401/402/403): permanent for that key, so the next provider gets its
    turn. A ``ValueError`` counts the same way: it is how a provider says
    it cannot take this recording at all — SpeechKit without its folder id
    or above the inline-body ceiling, an AssemblyAI job that came back
    failed — and replaying it costs the interview a provider that could
    have transcribed it. So does an ``AppError``: inside a provider call it
    is the platform's own refusal — the SSRF layer rejecting a tenant
    Whisper address that now resolves inside the perimeter or left the
    operator allowlist — and it will refuse the same way on every retry.
    Anything else (429, 5xx, timeouts) propagates, because it is transient
    and belongs to the caller's retry, not to a silent switch of the
    provider the tenant chose.

    Every provider that was called leaves a journal row, failed or not.
    """

    last_error = "no transcription provider configured"
    for provider in providers:
        started = time.perf_counter()
        try:
            result = await _run_provider(provider, audio_path, language=language)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            await _journal(provider, started, error_code=f"http_{code}")
            if code not in _PROVIDER_REFUSALS:
                raise
            last_error = f"{provider.provider_name} refused the request (HTTP {code})"
            logger.warning(
                "Transcription provider %s refused: HTTP %s",
                provider.provider_name,
                code,
            )
            continue
        except ValueError as exc:
            await _journal(provider, started, error_code=type(exc).__name__)
            last_error = f"{provider.provider_name} could not transcribe it: {exc}"
            logger.warning(
                "Transcription provider %s could not transcribe the recording: %s",
                provider.provider_name,
                exc,
            )
            continue
        except AppError as exc:
            await _journal(provider, started, error_code=exc.code)
            last_error = (
                f"{provider.provider_name} was refused by the platform: {exc.code}"
            )
            logger.warning(
                "Transcription provider %s refused by the platform: %s",
                provider.provider_name,
                exc.code,
            )
            continue
        except Exception as exc:
            await _journal(provider, started, error_code=type(exc).__name__)
            raise
        if result is None:
            # A size ceiling we could not split around: skip the provider,
            # not the interview. Nothing was sent, so nothing is journaled.
            last_error = (
                f"recording exceeds the {provider.provider_name} request size "
                "limit and could not be split"
            )
            continue
        await _journal(provider, started, result=result)
        return result, ""
    return None, last_error


__all__ = [
    "TranscriptionProvider",
    "TranscriptionResult",
    "TranscriptSegment",
    "OpenAIWhisperProvider",
    "DeepgramProvider",
    "AssemblyAIProvider",
    "get_transcription_chain_sync",
    "merge_chunk_results",
    "transcribe_with_chain",
]
