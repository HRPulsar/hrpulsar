"""Pluggable speech-to-text providers for the interview module.

Four providers are implemented:

- ``DeepgramProvider`` — the ``listen`` API with native speaker
  diarization, in one request.
- ``OpenAIWhisperProvider`` — the Whisper API. It does not diarize at
  all, so the transcript comes back single-voiced and the worker
  recovers the roles with an LLM pass (``speaker_roles``). Whisper also
  caps a request at 25 MB; a recording above it is split into chunks and
  stitched back together (HRP-646).
- ``AssemblyAIProvider`` — upload, then a polled transcript job, with
  native diarization.
- ``YandexSpeechKitProvider`` — v3 asynchronous file recognition with
  speaker labeling, for deployments that cannot send audio abroad.

``FasterWhisperProvider`` stays a stub: self-hosted whisper + pyannote
is the on-premise answer and has not been built yet.

Every credential a workspace has joins one chain (see
``get_transcription_chain_sync``), so a dead key costs a provider, not
the interview. A recording is only ever chunked for a provider that
declares ``max_request_bytes`` — the diarizing ones number speakers per
request, and splitting would rename them halfway through.
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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
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


class TranscriptionProvider(ABC):
    """Abstract base for speech-to-text providers."""

    provider_name: str = ""

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


class OpenAIWhisperProvider(TranscriptionProvider):
    provider_name = "whisper"

    # OpenAI Whisper rejects requests larger than 25 MB. Declared as the
    # provider's own property so the chain can split the recording for it
    # instead of writing the interview off.
    max_request_bytes = 25 * 1024 * 1024

    def __init__(self, api_key: str, model: str = "whisper-1") -> None:
        self._api_key = api_key
        self._model = model

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
                "model": self._model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
            # Omitted entirely when unknown: Whisper detects the
            # language itself, and a wrong hint is worse than none.
            if language:
                data["language"] = language
            async with httpx.AsyncClient(timeout=600) as http:
                response = await http.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files=files,
                )
        response.raise_for_status()
        body = response.json()

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
        audio_path: str,
        *,
        language: str | None = None,
        diarization: bool = True,
    ) -> TranscriptionResult:
        params: dict[str, Any] = {
            "model": self._model,
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
        self._model = model

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
            "model": self._model,
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


class FasterWhisperProvider(TranscriptionProvider):
    """Placeholder — self-hosted faster-whisper + pyannote, Phase R4."""

    provider_name = "faster_whisper"

    def __init__(self, endpoint: str | None = None) -> None:
        self._endpoint = endpoint

    async def transcribe(
        self,
        audio_path: str,
        *,
        language: str | None = None,
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
    "yandex_speechkit": YandexSpeechKitProvider,
    "faster_whisper": FasterWhisperProvider,
}

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
    provider: str, api_key: str, config: dict | None = None
) -> TranscriptionProvider:
    if provider not in _PROVIDER_REGISTRY:
        raise ValueError(f"Unknown transcription provider: {provider}")
    if provider == "whisper":
        return OpenAIWhisperProvider(api_key=api_key)
    if provider == "deepgram":
        return DeepgramProvider(api_key=api_key)
    if provider == "assemblyai":
        return AssemblyAIProvider(
            api_key=api_key,
            speakers_expected=int((config or {}).get("speakers_expected") or 0),
        )
    if provider == "yandex_speechkit":
        # SpeechKit addresses the account by folder, so the key alone is
        # not a credential: the tenant's row carries its own folder id,
        # and the platform folder is the fallback.
        folder_id = str((config or {}).get("folder_id") or "") or (
            settings.yandex_folder_id or ""
        )
        return YandexSpeechKitProvider(
            api_key=api_key,
            folder_id=folder_id,
            model=str((config or {}).get("model") or "general"),
        )
    if provider == "faster_whisper":
        return FasterWhisperProvider(endpoint=api_key or None)
    raise ValueError(f"Unknown transcription provider: {provider}")


def _tenant_key(row: TranscriptionProviderConfig) -> str:
    """Plaintext BYOK key of a row, falling back to the platform one.

    HRP-506: the column holds ciphertext — decrypting it here is what
    keeps a tenant BYOK key working (and keeps the ciphertext from
    travelling to the provider as a Bearer token). An unreadable key
    degrades to the platform credential, like the LLM dispatch path.
    """

    return decrypt_row_key(row, kind="transcription_provider") or _platform_key_for(
        row.provider
    )


def _provider_from_row(row: TranscriptionProviderConfig) -> TranscriptionProvider:
    return _build(row.provider, _tenant_key(row), row.settings)


def _default_provider() -> TranscriptionProvider:
    provider = settings.transcription_provider_default or "whisper"
    return _build(provider, _platform_key_for(provider))


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
        return _provider_from_row(row)
    return _default_provider()


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
        return _provider_from_row(row)
    return _default_provider()


def get_transcription_chain_sync(
    db: Session, tenant_id: uuid.UUID
) -> list[TranscriptionProvider]:
    """Every credential the workspace has, in the order they are tried.

    One dead credential used to take the whole feature down with it: the
    task resolved a single provider and a 401 from it was simply the end
    (2026-08 Deepgram account deactivation). The chain is the fallback —
    the caller walks it and only gives up when every provider has refused.

    A tenant's own keys come first, in ``_CHAIN_ORDER``, then the
    platform-keyed providers the tenant has not configured. Stubs are left
    out: they raise on call and would only mask the real error from the
    provider that actually tried.
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

    chain: list[TranscriptionProvider] = []
    for name in _CHAIN_ORDER:
        row = by_provider.get(name)
        if row is not None and _tenant_key(row):
            chain.append(_provider_from_row(row))
    for name in _CHAIN_ORDER:
        if name in by_provider or not _platform_key_for(name):
            continue
        chain.append(_build(name, _platform_key_for(name)))
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
    have transcribed it. Anything else (429, 5xx, timeouts) propagates,
    because it is transient and belongs to the caller's retry, not to a
    silent switch of the provider the tenant chose.
    """

    last_error = "no transcription provider configured"
    for provider in providers:
        try:
            result = await _run_provider(provider, audio_path, language=language)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _PROVIDER_REFUSALS:
                raise
            last_error = (
                f"{provider.provider_name} refused the request "
                f"(HTTP {exc.response.status_code})"
            )
            logger.warning(
                "Transcription provider %s refused: HTTP %s",
                provider.provider_name,
                exc.response.status_code,
            )
            continue
        except ValueError as exc:
            last_error = f"{provider.provider_name} could not transcribe it: {exc}"
            logger.warning(
                "Transcription provider %s could not transcribe the recording: %s",
                provider.provider_name,
                exc,
            )
            continue
        if result is None:
            # A size ceiling we could not split around: skip the provider,
            # not the interview.
            last_error = (
                f"recording exceeds the {provider.provider_name} request size "
                "limit and could not be split"
            )
            continue
        return result, ""
    return None, last_error


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
    "get_transcription_chain_sync",
    "merge_chunk_results",
    "transcribe_with_chain",
]
