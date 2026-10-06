"""Unit tests for app.modules.recruitment.transcription_service."""

import contextlib
import json

import pytest
from app.modules.recruitment.transcription_service import (
    AssemblyAIProvider,
    DeepgramProvider,
    OpenAIWhisperProvider,
    TranscriptionResult,
    TranscriptSegment,
    YandexSpeechKitProvider,
    _assemblyai_payload_to_result,
    _deepgram_payload_to_result,
    _whisper_payload_to_result,
    _yandex_payload_to_result,
)


@pytest.fixture(autouse=True)
def _every_processor_allowed(monkeypatch):
    """HRP-1005: the chain reads the tenant's processor list; the fake sync
    session cannot answer that query. The measured platform order unless a
    test picks a default (HRP-1007) — a developer's .env may set one."""
    from app.config import settings
    from app.modules.ai import processors

    monkeypatch.setattr(settings, "transcription_provider_default", "")
    monkeypatch.setattr(
        processors,
        "allowed_processors_sync",
        lambda db, tenant_id: frozenset(processors.PROCESSORS),
    )


def test_whisper_payload_parses_segments():
    body = {
        "text": "Hello world. How are you?",
        "language": "en",
        "duration": 12.5,
        "segments": [
            {"start": 0.0, "end": 3.0, "text": " Hello world."},
            {"start": 3.0, "end": 7.5, "text": " How are you?"},
        ],
    }
    result = _whisper_payload_to_result(body, provider="whisper")
    assert result.full_text == "Hello world. How are you?"
    assert result.duration_seconds == 12.5
    assert result.language == "en"
    assert result.provider == "whisper"
    assert len(result.segments) == 2
    assert result.segments[0].speaker == "speaker_0"
    assert result.segments[0].text == "Hello world."


def test_deepgram_payload_parses_diarized_utterances():
    body = {
        "metadata": {"duration": 60.0},
        "results": {
            "channels": [
                {
                    "detected_language": "es",
                    "alternatives": [{"transcript": "fallback transcript"}],
                }
            ],
            "utterances": [
                {
                    "speaker": 0,
                    "start": 0.0,
                    "end": 4.0,
                    "transcript": "Hola",
                    "confidence": 0.95,
                },
                {
                    "speaker": 1,
                    "start": 4.0,
                    "end": 8.0,
                    "transcript": "Hola, cuéntame sobre ti",
                    "confidence": 0.92,
                },
            ],
        },
    }
    result = _deepgram_payload_to_result(body, provider="deepgram")
    assert result.duration_seconds == 60.0
    assert result.language == "es"
    assert len(result.segments) == 2
    assert result.segments[0].speaker == "speaker_0"
    assert result.segments[1].speaker == "speaker_1"
    assert "Hola" in result.full_text


def test_deepgram_payload_falls_back_to_channel_transcript_when_no_utterances():
    body = {
        "metadata": {"duration": 5.0},
        "results": {
            "channels": [
                {
                    "alternatives": [{"transcript": "single channel"}],
                }
            ],
        },
    }
    result = _deepgram_payload_to_result(body, provider="deepgram")
    assert result.full_text == "single channel"
    assert result.segments == []


def test_provider_names_are_stable():
    assert OpenAIWhisperProvider.provider_name == "whisper"
    assert DeepgramProvider.provider_name == "deepgram"
    assert AssemblyAIProvider.provider_name == "assemblyai"


def test_whisper_provider_exposes_25mb_cap():
    """The Whisper API rejects payloads above 25 MB. It is declared as the
    provider's own ceiling so the chain knows to split the recording for
    it instead of writing the interview off (HRP-646)."""

    assert OpenAIWhisperProvider.max_request_bytes == 25 * 1024 * 1024
    assert DeepgramProvider.max_request_bytes is None


@pytest.fixture
def audio_file(tmp_path):
    """A small local mp3 — what the worker hands a provider (HRP-646)."""
    path = tmp_path / "interview.mp3"
    path.write_bytes(b"ID3" + b"\x00" * 1024)
    return str(path)


@pytest.mark.asyncio
async def test_whisper_provider_refuses_a_file_over_25mb(tmp_path):
    """Pre-flight guard: an oversized file must raise before the upload,
    not after a 26 MB request comes back rejected."""

    path = tmp_path / "long.mp3"
    with open(path, "wb") as handle:
        handle.truncate(26 * 1024 * 1024)

    provider = OpenAIWhisperProvider(api_key="x")
    with pytest.raises(ValueError, match="25 MB"):
        await provider.transcribe(str(path))


# ---------------------------------------------------------------------------
# R3b M-3: adversarial httpx mocks (401 / 429 / timeout) for both providers
# ---------------------------------------------------------------------------


def _streaming_client_factory(total_bytes: int = 1024) -> type:
    """Build a fake httpx.AsyncClient class that answers the POST leg with
    a user-supplied response object.

    Returned class is meant to be installed via
    ``monkeypatch.setattr(httpx, 'AsyncClient', factory())`` after setting
    ``post_response`` on it.
    """

    class _Client:
        post_response: object | None = None

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            resp = type(self).post_response
            if isinstance(resp, BaseException):
                raise resp
            return resp

        @contextlib.asynccontextmanager
        async def stream(self, method, *args, **kwargs):
            yield await self.post(*args, **kwargs)

    return _Client


class _RecordingClient:
    """Fake client that records the POST leg's kwargs."""

    post_response: object | None = None
    last_post: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        type(self).last_post = {"args": args, "kwargs": kwargs}
        resp = type(self).post_response
        if isinstance(resp, BaseException):
            raise resp
        return resp

    @contextlib.asynccontextmanager
    async def stream(self, method, *args, **kwargs):
        yield await self.post(*args, **kwargs)


class _FakeTextResponse:
    """Response whose body is read as text (the SpeechKit NDJSON stream)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class _FakeResponse:
    """Minimal httpx.Response stand-in for the provider tests."""

    def __init__(self, status_code: int, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_body or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("POST", "https://api.test/x")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )

    def json(self) -> dict:
        return self._json

    async def aiter_bytes(self):
        yield json.dumps(self._json).encode()


@pytest.mark.asyncio
async def test_whisper_provider_propagates_401_unauthorized(monkeypatch, audio_file):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = _FakeResponse(401)
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = OpenAIWhisperProvider(api_key="bad")
    with pytest.raises(httpx.HTTPStatusError):
        await provider.transcribe(audio_file)


@pytest.mark.asyncio
async def test_whisper_provider_propagates_429_rate_limit(monkeypatch, audio_file):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = _FakeResponse(429)
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = OpenAIWhisperProvider(api_key="x")
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await provider.transcribe(audio_file)
    assert "429" in str(exc.value)


@pytest.mark.asyncio
async def test_whisper_provider_surfaces_request_timeout(monkeypatch, audio_file):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = httpx.ReadTimeout(
        "timed out", request=httpx.Request("POST", "https://api.test/x")
    )
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = OpenAIWhisperProvider(api_key="x")
    with pytest.raises(httpx.ReadTimeout):
        await provider.transcribe(audio_file)


@pytest.mark.asyncio
async def test_deepgram_provider_propagates_401(monkeypatch, audio_file):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = _FakeResponse(401)
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = DeepgramProvider(api_key="bad")
    with pytest.raises(httpx.HTTPStatusError):
        await provider.transcribe(audio_file)


@pytest.mark.asyncio
async def test_deepgram_provider_propagates_429(monkeypatch, audio_file):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = _FakeResponse(429)
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = DeepgramProvider(api_key="x")
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await provider.transcribe(audio_file)
    assert "429" in str(exc.value)


@pytest.mark.asyncio
async def test_deepgram_provider_surfaces_timeout(monkeypatch, audio_file):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = httpx.ConnectTimeout(
        "deepgram unreachable",
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = DeepgramProvider(api_key="x")
    with pytest.raises(httpx.ConnectTimeout):
        await provider.transcribe(audio_file)


# ---------------------------------------------------------------------------
# BYOK key handling (HRP-506)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2026-08 follow-up: audio goes as bytes, language is not hardcoded, and a
# refused credential falls through to the next provider.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepgram_posts_audio_bytes_not_a_storage_url(monkeypatch, audio_file):
    """Deepgram must never be handed a presigned URL to fetch itself.

    Sending the link exposed the storage host to a third party and forced
    the bucket to be reachable from their cloud; the worker streams the
    bytes instead, tagged with the object's own content type.
    """
    import httpx

    _RecordingClient.post_response = _FakeResponse(200, {"results": {}})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)

    await DeepgramProvider(api_key="x").transcribe(audio_file)

    kwargs = _RecordingClient.last_post["kwargs"]
    assert "json" not in kwargs, "the URL must not be posted to the provider"
    assert kwargs["content"] is not None
    assert kwargs["headers"]["Content-Type"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_deepgram_detects_language_when_none_is_configured(monkeypatch, audio_file):
    import httpx

    _RecordingClient.post_response = _FakeResponse(200, {"results": {}})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)

    await DeepgramProvider(api_key="x").transcribe(audio_file)
    params = _RecordingClient.last_post["kwargs"]["params"]
    assert params["detect_language"] == "true"
    assert "language" not in params

    await DeepgramProvider(api_key="x").transcribe(
        audio_file, language="ru"
    )
    params = _RecordingClient.last_post["kwargs"]["params"]
    assert params["language"] == "ru"
    assert "detect_language" not in params


@pytest.mark.asyncio
async def test_whisper_omits_the_language_field_when_unknown(monkeypatch, audio_file):
    """A wrong language hint is worse than none — Whisper detects it."""
    import httpx

    _RecordingClient.post_response = _FakeResponse(200, {"text": "hi"})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)

    await OpenAIWhisperProvider(api_key="x").transcribe(audio_file)
    assert "language" not in _RecordingClient.last_post["kwargs"]["data"]

    await OpenAIWhisperProvider(api_key="x").transcribe(
        audio_file, language="de"
    )
    assert _RecordingClient.last_post["kwargs"]["data"]["language"] == "de"


class _StubProvider:
    """Provider double: either refuses with a status, or returns a result."""

    def __init__(
        self,
        name: str,
        refuses: int | None = None,
        max_request_bytes: int | None = None,
        rejects: str | None = None,
    ) -> None:
        self.provider_name = name
        self.max_request_bytes = max_request_bytes
        self._refuses = refuses
        self._rejects = rejects
        self.calls = 0
        self.seen_paths: list[str] = []

    async def transcribe(self, audio_path, *, language=None, diarization=True):
        self.calls += 1
        self.seen_paths.append(audio_path)
        if self._rejects is not None:
            raise ValueError(self._rejects)
        if self._refuses is not None:
            _FakeResponse(self._refuses).raise_for_status()
        return TranscriptionResult(
            full_text="ok",
            segments=[
                TranscriptSegment(
                    speaker="speaker_0", start=0.0, end=5.0, text=f"chunk {self.calls}"
                )
            ],
            provider=self.provider_name,
        )


@pytest.mark.asyncio
async def test_chain_moves_past_a_refused_credential():
    """The 2026-08 outage in one call: a deactivated key must not take the
    feature down when another provider is configured."""
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    dead = _StubProvider("deepgram", refuses=401)
    alive = _StubProvider("whisper")

    result, err = await transcribe_with_chain([dead, alive], "https://signed/x")

    assert result is not None and result.provider == "whisper"
    assert err == ""
    assert dead.calls == 1 and alive.calls == 1


@pytest.mark.asyncio
async def test_chain_reports_failure_when_every_provider_refuses():
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    result, err = await transcribe_with_chain(
        [_StubProvider("deepgram", refuses=401), _StubProvider("whisper", refuses=402)],
        "https://signed/x",
    )

    assert result is None
    assert "whisper refused" in err


@pytest.mark.asyncio
async def test_chain_moves_on_when_a_provider_cannot_take_the_recording():
    """A provider's own "I cannot do this" is deterministic — SpeechKit
    without a folder id, an AssemblyAI job that came back failed — so it
    costs that provider, not the interview (HRP-646 follow-up)."""
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    rejecting = _StubProvider("yandex_speechkit", rejects="needs a folder id")
    alive = _StubProvider("whisper")

    result, err = await transcribe_with_chain([rejecting, alive], "https://signed/x")

    assert result is not None and result.provider == "whisper"
    assert err == ""
    assert rejecting.calls == 1 and alive.calls == 1


@pytest.mark.asyncio
async def test_chain_reports_the_last_rejection_when_every_provider_declines():
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    result, err = await transcribe_with_chain(
        [_StubProvider("assemblyai", rejects="corrupt audio")], "https://signed/x"
    )

    assert result is None
    assert "assemblyai" in err and "corrupt audio" in err


@pytest.mark.asyncio
async def test_chain_does_not_swallow_a_transient_error():
    """429 and 5xx belong to the Celery retry against the tenant's own
    provider — silently switching providers would hide a rate limit."""
    import httpx
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    throttled = _StubProvider("deepgram", refuses=429)
    other = _StubProvider("whisper")

    with pytest.raises(httpx.HTTPStatusError):
        await transcribe_with_chain([throttled, other], "https://signed/x")
    assert other.calls == 0


@pytest.mark.asyncio
async def test_chain_skips_a_capped_provider_when_the_file_cannot_be_split(
    tmp_path, monkeypatch
):
    """Whisper's 25 MB ceiling belongs to Whisper, not to the interview —
    and with no ffmpeg to split around it, the next provider takes over."""
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.transcription_service import (
        OpenAIWhisperProvider,
        transcribe_with_chain,
    )

    path = tmp_path / "long.mp3"
    with open(path, "wb") as handle:
        handle.truncate(OpenAIWhisperProvider.max_request_bytes + 1)
    monkeypatch.setattr(
        transcription_service, "split_audio", lambda *a, **kw: []
    )

    whisper = OpenAIWhisperProvider(api_key="x")
    deepgram = _StubProvider("deepgram")

    result, _ = await transcribe_with_chain([whisper, deepgram], str(path))

    assert result is not None and result.provider == "deepgram"


@pytest.mark.asyncio
async def test_chain_splits_an_oversized_recording_and_shifts_the_timecodes(
    tmp_path, monkeypatch
):
    """HRP-646: over the provider's ceiling the recording is cut, each
    chunk transcribed, and the pieces put back on one clock."""
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    path = tmp_path / "long.mp3"
    with open(path, "wb") as handle:
        handle.truncate(30 * 1024 * 1024)
    monkeypatch.setattr(
        transcription_service,
        "split_audio",
        lambda *a, **kw: [("/tmp/chunk_000.mp3", 0.0), ("/tmp/chunk_001.mp3", 600.0)],
    )

    capped = _StubProvider("whisper", max_request_bytes=25 * 1024 * 1024)
    result, err = await transcribe_with_chain([capped], str(path))

    assert err == ""
    assert result is not None
    assert capped.seen_paths == ["/tmp/chunk_000.mp3", "/tmp/chunk_001.mp3"]
    assert [seg.start for seg in result.segments] == [0.0, 600.0]
    assert result.full_text == "chunk 1 chunk 2"


@pytest.mark.asyncio
async def test_chain_hands_a_provider_without_a_ceiling_the_whole_file(tmp_path):
    """Deepgram takes large files and numbers speakers per request, so it
    is never chunked — cutting it would make speaker_0 of the second chunk
    a different person."""
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    path = tmp_path / "long.mp3"
    with open(path, "wb") as handle:
        handle.truncate(300 * 1024 * 1024)

    deepgram = _StubProvider("deepgram")
    result, _ = await transcribe_with_chain([deepgram], str(path))

    assert result is not None
    assert deepgram.seen_paths == [str(path)]


def test_merge_drops_what_the_chunk_overlap_transcribed_twice():
    """The seam is transcribed by both chunks on purpose; the merge keeps
    one copy and puts every timecode back on the recording's clock."""
    from app.modules.recruitment.transcription_service import merge_chunk_results

    first = TranscriptionResult(
        full_text="one two",
        segments=[
            TranscriptSegment(speaker="speaker_0", start=0.0, end=10.0, text="one"),
            TranscriptSegment(speaker="speaker_0", start=10.0, end=20.0, text="two"),
        ],
        language="ru",
        provider="whisper",
    )
    second = TranscriptionResult(
        full_text="two three",
        segments=[
            # The overlap: the same "two", now 15 s into the second chunk.
            TranscriptSegment(speaker="speaker_0", start=0.0, end=5.0, text="two"),
            TranscriptSegment(speaker="speaker_0", start=5.0, end=12.0, text="three"),
        ],
        provider="whisper",
    )


    merged = merge_chunk_results([(first, 0.0), (second, 15.0)])

    assert [seg.text for seg in merged.segments] == ["one", "two", "three"]
    assert [seg.start for seg in merged.segments] == [0.0, 10.0, 20.0]
    assert merged.full_text == "one two three"
    assert merged.duration_seconds == 27.0
    assert merged.language == "ru"
    assert merged.provider == "whisper"


def test_merge_keeps_the_segment_that_straddles_the_seam():
    """Dropping everything that starts before the previous chunk ended
    swallowed a whole sentence of a real interview: the segment across the
    boundary is mostly new speech, so it stays."""
    from app.modules.recruitment.transcription_service import merge_chunk_results

    first = TranscriptionResult(
        full_text="cut here",
        segments=[
            TranscriptSegment(
                speaker="speaker_0", start=78.0, end=90.0, text="cut here"
            )
        ],
        provider="whisper",
    )
    # Chunk two starts at 85 s: its first segment runs 85 -> 96, i.e. only
    # its first five seconds are already transcribed.
    second = TranscriptionResult(
        full_text="the sentence that was lost",
        segments=[
            TranscriptSegment(
                speaker="speaker_0",
                start=0.0,
                end=11.0,
                text="the sentence that was lost",
            )
        ],
        provider="whisper",
    )

    merged = merge_chunk_results([(first, 0.0), (second, 85.0)])

    assert [seg.text for seg in merged.segments] == [
        "cut here",
        "the sentence that was lost",
    ]


def test_chain_walks_every_configured_credential_in_order(monkeypatch):
    """A dead credential must not be the end of the feature (2026-08).

    Order is assemblyai → deepgram → yandex_speechkit → whisper, and a
    provider with no key at all is left out rather than 401-ing on every
    single interview (HRP-646)."""
    import uuid as _uuid

    from app.modules.recruitment import transcription_service

    monkeypatch.setattr(transcription_service.settings, "deepgram_api_key", "dg")
    monkeypatch.setattr(transcription_service.settings, "openai_api_key", "oa")
    monkeypatch.setattr(transcription_service.settings, "assemblyai_api_key", "aai")
    monkeypatch.setattr(
        transcription_service.settings, "yandex_speechkit_api_key", "yc"
    )
    monkeypatch.setattr(transcription_service.settings, "yandex_folder_id", "b1g")

    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([]), _uuid.uuid4()
    )
    assert [p.provider_name for p in chain] == [
        "assemblyai",
        "deepgram",
        "yandex_speechkit",
        "whisper",
    ]

    monkeypatch.setattr(transcription_service.settings, "openai_api_key", "")
    monkeypatch.setattr(transcription_service.settings, "assemblyai_api_key", "")
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([]), _uuid.uuid4()
    )
    assert [p.provider_name for p in chain] == ["deepgram", "yandex_speechkit"]


def test_chain_puts_the_tenants_own_keys_ahead_of_platform_ones(monkeypatch):
    """A workspace that brought its own AssemblyAI key pays with it first,
    even though the platform has a Deepgram key earlier in the order."""
    import uuid as _uuid

    from app.core.crypto import encrypt_secret
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(transcription_service.settings, "deepgram_api_key", "dg")
    monkeypatch.setattr(transcription_service.settings, "openai_api_key", "oa")
    monkeypatch.setattr(transcription_service.settings, "assemblyai_api_key", "")
    monkeypatch.setattr(
        transcription_service.settings, "yandex_speechkit_api_key", ""
    )
    monkeypatch.setattr(transcription_service.settings, "yandex_api_key", "")

    row = TranscriptionProviderConfig(
        provider="assemblyai",
        api_key_encrypted=encrypt_secret("tenant-aai"),
        is_active=True,
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )

    assert [p.provider_name for p in chain] == ["assemblyai", "deepgram", "whisper"]
    assert chain[0]._api_key == "tenant-aai"


def test_chain_leaves_out_processors_the_tenant_may_not_use(monkeypatch):
    import uuid as _uuid

    from app.modules.ai import processors
    from app.modules.recruitment import transcription_service

    monkeypatch.setattr(transcription_service.settings, "deepgram_api_key", "dg")
    monkeypatch.setattr(transcription_service.settings, "openai_api_key", "oa")
    monkeypatch.setattr(
        processors, "allowed_processors_sync", lambda db, tenant_id: frozenset({"deepgram"})
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([]), _uuid.uuid4()
    )
    assert [p.provider_name for p in chain] == ["deepgram"]


def test_chain_keyless_row_with_denied_processor_stays_out(monkeypatch):
    """F1 regression: the chain's own key lookup used to fall back to the
    platform key inline, so a row with no key (or an undecryptable one)
    dispatched on the platform key without ever going through the
    processor check — that check only covered the fallback loop for
    unconfigured providers."""
    import uuid as _uuid

    from app.modules.ai import processors
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(
        transcription_service.settings, "deepgram_api_key", "platform-dg"
    )
    monkeypatch.setattr(
        processors, "allowed_processors_sync", lambda db, tenant_id: frozenset()
    )
    row = TranscriptionProviderConfig(
        provider="deepgram", api_key_encrypted=None, is_active=True
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert chain == []


def test_chain_keyed_row_with_denied_processor_stays_in(monkeypatch):
    """BYOK is never restricted by the processor list (HRP-1005 R4) — a
    tenant's own key must still dispatch even when the instance has since
    disallowed that processor for platform-keyed calls."""
    import uuid as _uuid

    from app.core.crypto import encrypt_secret
    from app.modules.ai import processors
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(
        processors, "allowed_processors_sync", lambda db, tenant_id: frozenset()
    )
    row = TranscriptionProviderConfig(
        provider="deepgram",
        api_key_encrypted=encrypt_secret("dg-tenant-key"),
        is_active=True,
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert [p.provider_name for p in chain] == ["deepgram"]
    assert chain[0]._api_key == "dg-tenant-key"


def test_chain_keyless_row_with_allowed_processor_uses_platform_key(monkeypatch):
    """F14: the mirror case of F1 — a keyless row whose processor IS
    allowed must still fall back to the platform key (not silently drop
    it), carrying the row's own ``settings`` (e.g. ``speakers_expected``)
    the way the tenant configured it, not the bare defaults the
    unconfigured-provider loop below would use."""
    import uuid as _uuid

    from app.modules.ai import processors
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(
        transcription_service.settings, "assemblyai_api_key", "platform-aai"
    )
    monkeypatch.setattr(
        processors,
        "allowed_processors_sync",
        lambda db, tenant_id: frozenset({"assemblyai"}),
    )
    row = TranscriptionProviderConfig(
        provider="assemblyai",
        api_key_encrypted=None,
        is_active=True,
        settings={"speakers_expected": 3},
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert [p.provider_name for p in chain] == ["assemblyai"]
    assert chain[0]._api_key == "platform-aai"
    assert chain[0]._speakers_expected == 3


def test_chain_undecryptable_row_with_allowed_processor_uses_platform_key(
    monkeypatch,
):
    """A key that no longer decrypts (ENCRYPTION_KEY rotation) must degrade
    to the platform key exactly like a keyless row, when the processor is
    allowed."""
    import uuid as _uuid

    from app.modules.ai import processors
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(
        transcription_service.settings, "deepgram_api_key", "platform-dg"
    )
    monkeypatch.setattr(
        processors,
        "allowed_processors_sync",
        lambda db, tenant_id: frozenset({"deepgram"}),
    )
    row = TranscriptionProviderConfig(
        provider="deepgram",
        api_key_encrypted="not-a-valid-ciphertext",
        is_active=True,
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert [p.provider_name for p in chain] == ["deepgram"]
    assert chain[0]._api_key == "platform-dg"


def test_chain_keyless_row_with_allowed_processor_but_no_platform_key_stays_out(
    monkeypatch,
):
    """Allowed is necessary but not sufficient: without a platform key
    there is nothing to fall back to, so the row must not appear."""
    import uuid as _uuid

    from app.modules.ai import processors
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(transcription_service.settings, "deepgram_api_key", "")
    monkeypatch.setattr(
        processors,
        "allowed_processors_sync",
        lambda db, tenant_id: frozenset({"deepgram"}),
    )
    row = TranscriptionProviderConfig(
        provider="deepgram", api_key_encrypted=None, is_active=True
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert chain == []


def test_assemblyai_speaker_count_comes_from_the_tenant_row(monkeypatch):
    """A panel interview is configured, not hardcoded: the provider row
    carries the number of voices to expect."""
    import uuid as _uuid

    from app.core.crypto import encrypt_secret
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    row = TranscriptionProviderConfig(
        provider="assemblyai",
        api_key_encrypted=encrypt_secret("aai"),
        is_active=True,
        settings={"speakers_expected": 4},
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert chain[0]._speakers_expected == 4

    row.settings = None
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert chain[0]._speakers_expected == 2


def test_yandex_provider_carries_the_folder_from_the_tenant_row(monkeypatch):
    """SpeechKit addresses the account by folder: the key alone is not a
    credential, so the row's own folder id must reach the provider."""
    import uuid as _uuid

    from app.core.crypto import encrypt_secret
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(transcription_service.settings, "yandex_folder_id", "platform")
    row = TranscriptionProviderConfig(
        provider="yandex_speechkit",
        api_key_encrypted=encrypt_secret("yc-key"),
        is_active=True,
        settings={"folder_id": "b1gtenant"},
    )

    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert chain[0]._folder_id == "b1gtenant"

    row.settings = None
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert chain[0]._folder_id == "platform"


class _FakeSyncResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSyncSession:
    """Stand-in for the worker's sync Session.

    Accepts either a single row or a list, because the chain reads every
    configured provider while the single-provider resolvers read one.
    """

    def __init__(self, rows):
        if rows is None:
            rows = []
        self._rows = rows if isinstance(rows, list) else [rows]

    def execute(self, _query):
        return _FakeSyncResult(self._rows)


def test_byok_transcription_key_is_decrypted(monkeypatch):
    """The stored column is ciphertext — the provider must receive the
    plaintext key, never the blob (HRP-506)."""
    import uuid as _uuid

    from app.core.crypto import encrypt_secret
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    row = TranscriptionProviderConfig(
        provider="deepgram",
        api_key_encrypted=encrypt_secret("dg-tenant-key"),
        is_active=True,
    )
    chain = transcription_service.get_transcription_chain_sync(
        _FakeSyncSession([row]), _uuid.uuid4()
    )
    assert chain[0]._api_key == "dg-tenant-key"


# ---------------------------------------------------------------------------
# AssemblyAI and Yandex SpeechKit (HRP-646)
# ---------------------------------------------------------------------------


def test_assemblyai_payload_parses_diarized_utterances():
    """Their labels are letters and their clock is milliseconds; ours are
    speaker_N and seconds."""
    body = {
        "status": "completed",
        "language_code": "ru",
        "audio_duration": 92.0,
        "text": "fallback",
        "utterances": [
            {
                "speaker": "A",
                "start": 1500,
                "end": 4000,
                "text": "Tell me about yourself",
                "confidence": 0.94,
            },
            {
                "speaker": "B",
                "start": 4200,
                "end": 9000,
                "text": "I led the team",
                "confidence": 0.91,
            },
            {"speaker": "A", "start": 9100, "end": 9500, "text": "  "},
        ],
    }

    result = _assemblyai_payload_to_result(body, provider="assemblyai")

    assert [seg.speaker for seg in result.segments] == ["speaker_0", "speaker_1"]
    assert result.segments[0].start == 1.5
    assert result.segments[1].end == 9.0
    assert result.language == "ru"
    assert result.duration_seconds == 92.0
    assert result.full_text == "Tell me about yourself I led the team"


def test_assemblyai_payload_falls_back_to_plain_text():
    body = {"status": "completed", "text": "single blob", "utterances": []}
    result = _assemblyai_payload_to_result(body, provider="assemblyai")
    assert result.full_text == "single blob"
    assert result.segments == []


@pytest.mark.asyncio
async def test_assemblyai_uploads_bytes_then_polls_until_completed(
    monkeypatch, audio_file
):
    """Upload, create, poll: the storage URL never leaves the platform, and
    a job still processing is waited out rather than read as empty."""
    import httpx

    calls = []

    class _Client:
        def __init__(self, *a, **kw) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            if url.endswith("/upload"):
                return _FakeResponse(200, {"upload_url": "https://aai/tmp/1"})
            return _FakeResponse(200, {"id": "t-1", "status": "queued"})

        async def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            if len([c for c in calls if c[0] == "GET"]) == 1:
                return _FakeResponse(200, {"status": "processing"})
            return _FakeResponse(
                200,
                {
                    "status": "completed",
                    "text": "hi",
                    "utterances": [
                        {"speaker": "A", "start": 0, "end": 1000, "text": "hi"}
                    ],
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(AssemblyAIProvider, "_POLL_INTERVAL_SECONDS", 0.0)

    result = await AssemblyAIProvider(api_key="k").transcribe(
        audio_file, language="ru"
    )

    upload = calls[0]
    assert upload[1].endswith("/upload")
    assert upload[2]["content"] is not None, "audio must go as bytes"
    created = calls[1][2]["json"]
    assert created["audio_url"] == "https://aai/tmp/1"
    assert created["speaker_labels"] is True
    # Without the hint a Russian interview comes back as one voice.
    assert created["speakers_expected"] == 2
    assert created["language_code"] == "ru"
    assert "language_detection" not in created
    assert result.provider == "assemblyai"
    assert result.segments[0].speaker == "speaker_0"


@pytest.mark.asyncio
async def test_assemblyai_surfaces_a_failed_job(monkeypatch, audio_file):
    import httpx

    class _Client:
        def __init__(self, *a, **kw) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            if url.endswith("/upload"):
                return _FakeResponse(200, {"upload_url": "https://aai/tmp/1"})
            return _FakeResponse(200, {"id": "t-1"})

        async def get(self, url, **kwargs):
            return _FakeResponse(200, {"status": "error", "error": "corrupt audio"})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    with pytest.raises(ValueError, match="corrupt audio"):
        await AssemblyAIProvider(api_key="k").transcribe(audio_file)


def _yc_line(channel, index, text, words, kind="final"):
    """One line of the getRecognition stream, shaped like the real one."""
    alternative = {
        "text": text,
        # Not when the speech starts: where the previous final of this
        # channel ended. The real span is in the words.
        "startTimeMs": "0",
        "endTimeMs": words[-1][1],
        "words": [
            {"text": w, "startTimeMs": start, "endTimeMs": end}
            for w, (start, end) in zip(
                text.split(), [(a, b) for a, b in words], strict=False
            )
        ],
    }
    body = (
        {"final": {"alternatives": [alternative]}}
        if kind == "final"
        else {
            "finalRefinement": {
                "finalIndex": index,
                "normalizedText": {"alternatives": [alternative]},
            }
        }
    )
    return json.dumps(
        {
            "result": {
                "channelTag": channel,
                "audioCursors": {"finalIndex": index},
                **body,
            }
        }
    )


def test_yandex_payload_parses_the_real_ndjson_stream():
    """Shaped after an actual SpeechKit recognition (HRP-646).

    With speaker labeling on, each voice gets its own channelTag and its
    own finalIndex sequence — that tag is the diarization, there is no
    speakerTag in the payload at all.
    """
    raw = "\n".join(
        [
            _yc_line("1", "0", "you answered", [("229", "320"), ("380", "1079")]),
            _yc_line(
                "1",
                "0",
                "You answered.",
                [("229", "320"), ("380", "1079")],
                kind="refinement",
            ),
            json.dumps(
                {
                    "result": {
                        "channelTag": "1",
                        "audioCursors": {"finalIndex": "0", "eouTimeMs": "1079"},
                        "eouUpdate": {},
                    }
                }
            ),
            # The other voice: its own channel, its own index sequence, and
            # it starts ten seconds after the first one finished.
            _yc_line(
                "0", "0", "yes all right", [("10160", "10500"), ("10600", "48960")]
            ),
            _yc_line(
                "0",
                "0",
                "Yes, all right.",
                [("10160", "10500"), ("10600", "48960")],
                kind="refinement",
            ),
            _yc_line("1", "2", "mhm", [("52420", "52760")]),
            "",
        ]
    )

    result = _yandex_payload_to_result(raw, provider="yandex_speechkit")

    # Chronological, not stream order: the channels are interleaved.
    assert [seg.start for seg in result.segments] == [0.229, 10.16, 52.42]
    assert [seg.speaker for seg in result.segments] == [
        "speaker_0",
        "speaker_1",
        "speaker_0",
    ]
    # The refinement replaced the raw text instead of doubling the segment.
    assert [seg.text for seg in result.segments] == [
        "You answered.",
        "Yes, all right.",
        "mhm",
    ]
    assert result.full_text == "You answered. Yes, all right. mhm"
    assert result.duration_seconds == 52.76


def test_yandex_payload_survives_a_recording_it_did_not_separate():
    """No speaker labeling, or a voice it could not split: one channel, one
    speaker — and the worker's LLM role pass takes it from there."""
    raw = "\n".join(
        [
            _yc_line("0", "0", "first turn", [("100", "900")]),
            _yc_line("0", "1", "second turn", [("1000", "1900")]),
        ]
    )

    result = _yandex_payload_to_result(raw, provider="yandex_speechkit")

    assert {seg.speaker for seg in result.segments} == {"speaker_0"}
    assert len(result.segments) == 2


@pytest.mark.asyncio
async def test_yandex_refuses_without_a_folder_id(audio_file):
    with pytest.raises(ValueError, match="folder id"):
        await YandexSpeechKitProvider(api_key="k").transcribe(audio_file)


@pytest.mark.asyncio
async def test_yandex_sends_mono_full_data_with_speaker_labeling(
    monkeypatch, audio_file
):
    """Speaker labeling only exists in FULL_DATA mode — sending anything
    else would quietly return a transcript with no speakers at all."""
    import httpx

    sent = {}

    class _Client:
        def __init__(self, *a, **kw) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            sent["body"] = kwargs["json"]
            sent["headers"] = kwargs["headers"]
            return _FakeResponse(200, {"id": "op-1"})

        async def get(self, url, **kwargs):
            if "operations" in url:
                return _FakeResponse(200, {"done": True})
            return _FakeTextResponse(
                json.dumps(
                    {
                        "result": {
                            "final": {"alternatives": [{"text": "ok"}]},
                        }
                    }
                )
            )

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    result = await YandexSpeechKitProvider(
        api_key="k", folder_id="b1g"
    ).transcribe(audio_file, language="ru")

    assert sent["headers"]["Authorization"] == "Api-Key k"
    assert sent["headers"]["x-folder-id"] == "b1g"
    model = sent["body"]["recognitionModel"]
    assert model["audioProcessingType"] == "FULL_DATA"
    assert model["languageRestriction"]["languageCode"] == ["ru-RU"]
    assert sent["body"]["speakerLabeling"] == {
        "speakerLabeling": "SPEAKER_LABELING_ENABLED"
    }
    assert sent["body"]["content"], "audio travels inline, base64 encoded"
    assert result.provider == "yandex_speechkit"


@pytest.mark.asyncio
async def test_yandex_leaves_the_language_open_when_it_has_no_locale(
    monkeypatch, audio_file
):
    """SpeechKit wants a locale; a language it does not know is better left
    to detection than sent as an invented locale."""
    import httpx

    sent = {}

    class _Client:
        def __init__(self, *a, **kw) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            sent["body"] = kwargs["json"]
            return _FakeResponse(200, {"id": "op-1"})

        async def get(self, url, **kwargs):
            if "operations" in url:
                return _FakeResponse(200, {"done": True})
            return _FakeTextResponse("")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    await YandexSpeechKitProvider(api_key="k", folder_id="b1g").transcribe(
        audio_file, language="de"
    )

    assert "languageRestriction" not in sent["body"]["recognitionModel"]


def test_providers_with_native_diarization_declare_no_size_ceiling():
    """Chunking a diarizing provider would renumber its speakers halfway
    through the interview — the ceiling is what triggers chunking, so they
    must not declare one."""
    assert DeepgramProvider.max_request_bytes is None
    assert AssemblyAIProvider.max_request_bytes is None
    assert YandexSpeechKitProvider.max_request_bytes is None


# ---------------------------------------------------------------------------
# HRP-985: the tenant's own Whisper server; no stub in the chain
# ---------------------------------------------------------------------------


def _platform_keys(monkeypatch, default=""):
    """Every provider has a platform key; ``default`` is the operator's pick."""
    from app.modules.recruitment import transcription_service

    s = transcription_service.settings
    monkeypatch.setattr(s, "assemblyai_api_key", "aai")
    monkeypatch.setattr(s, "deepgram_api_key", "dg")
    monkeypatch.setattr(s, "yandex_speechkit_api_key", "yc")
    monkeypatch.setattr(s, "yandex_folder_id", "b1g")
    monkeypatch.setattr(s, "openai_api_key", "oa")
    monkeypatch.setattr(s, "transcription_provider_default", default)
    return transcription_service


def _chain(transcription_service, *rows):
    import uuid as _uuid

    return transcription_service.get_transcription_chain_sync(
        _FakeSyncSession(list(rows)), _uuid.uuid4()
    )


def _row(provider, key=None, **provider_settings):
    from app.core.crypto import encrypt_secret
    from app.modules.recruitment.models import TranscriptionProviderConfig

    return TranscriptionProviderConfig(
        provider=provider,
        api_key_encrypted=encrypt_secret(key) if key else None,
        is_active=True,
        settings=provider_settings or None,
    )


@pytest.mark.asyncio
async def test_whisper_posts_to_the_tenants_own_server(monkeypatch, audio_file):
    import httpx
    from app.modules.recruitment import transcription_service

    monkeypatch.setattr(transcription_service.settings, "deployment_mode", "onprem")
    _RecordingClient.post_response = _FakeResponse(200, {"text": "hi"})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)

    await OpenAIWhisperProvider(
        api_key="", base_url="http://whisper.lan:8000/v1/"
    ).transcribe(audio_file)

    sent = _RecordingClient.last_post
    assert sent["args"][0] == "http://whisper.lan:8000/v1/audio/transcriptions"
    # A local server without auth gets no empty bearer token.
    assert "Authorization" not in sent["kwargs"]["headers"]


@pytest.mark.asyncio
async def test_whisper_without_an_address_is_openai(monkeypatch, audio_file):
    import httpx

    _RecordingClient.post_response = _FakeResponse(200, {"text": "hi"})
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)

    await OpenAIWhisperProvider(api_key="sk-x").transcribe(audio_file)

    sent = _RecordingClient.last_post
    assert sent["args"][0] == "https://api.openai.com/v1/audio/transcriptions"
    assert sent["kwargs"]["headers"] == {"Authorization": "Bearer sk-x"}


@pytest.mark.asyncio
async def test_a_tenant_whisper_address_goes_through_the_ssrf_client(
    monkeypatch, audio_file
):
    """The request-time half of the LLM base_url guard (HRP-505) covers the
    Whisper address too; OpenAI itself does not need it."""
    from app.core import url_guard

    calls = []

    def _guarded(base_url, *, error_code, timeout=None):
        calls.append((base_url, error_code))
        return _RecordingClient()

    monkeypatch.setattr(url_guard, "tenant_endpoint_http_client", _guarded)
    _RecordingClient.post_response = _FakeResponse(200, {"text": "hi"})

    await OpenAIWhisperProvider(
        api_key="k", base_url="https://stt.example.com/v1"
    ).transcribe(audio_file)
    assert calls == [("https://stt.example.com/v1", "llm_base_url_not_public")]

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)
    await OpenAIWhisperProvider(api_key="k").transcribe(audio_file)
    assert len(calls) == 1


class _RawResponse:
    status_code = 200

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    def raise_for_status(self) -> None:
        pass

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks",
    [
        (b"[1, 2]",),
        (b"<html>bad gateway</html>",),
        (b"{" + b" " * (8 * 1024 * 1024),) * 3,
    ],
    ids=["not-an-object", "not-json", "over-the-cap"],
)
async def test_a_bad_whisper_answer_is_a_provider_refusal(
    monkeypatch, audio_file, chunks
):
    """Review B4: a tenant server's body is read up to a cap and has to be
    a JSON object; anything else is a ValueError, which moves the chain on
    instead of retrying the upload."""
    import httpx

    _RecordingClient.post_response = _RawResponse(*chunks)
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)

    with pytest.raises(ValueError):
        await OpenAIWhisperProvider(api_key="k").transcribe(audio_file)


def test_a_platform_key_never_goes_to_a_tenant_address(monkeypatch):
    """A keyless Whisper row with an address is the tenant's own server: it
    runs there without a key, and the platform OpenAI key is not added
    behind it as a second Whisper."""
    ts = _platform_keys(monkeypatch)

    chain = _chain(ts, _row("whisper", base_url="http://whisper.lan/v1"))

    whisper = [p for p in chain if p.provider_name == "whisper"]
    assert len(whisper) == 1
    assert whisper[0]._api_key == ""
    assert whisper[0]._base_url == "http://whisper.lan/v1"
    assert whisper[0].credential_source == "local"
    # Built on the platform key, the same row settings drop the address.
    built = ts._build("whisper", "oa", {"base_url": "http://x/v1"}, source="platform")
    assert built._base_url is None


def test_a_tenant_whisper_server_gets_no_platform_fallback(monkeypatch):
    """Review B3: the tenant's own server failing must not ship the audio
    to a platform-keyed vendor; the tenant's own keys still follow."""
    ts = _platform_keys(monkeypatch)

    chain = _chain(
        ts,
        _row("whisper", base_url="http://whisper.lan/v1"),
        _row("deepgram", key="dg-own"),
    )

    assert [(p.provider_name, p.credential_source) for p in chain] == [
        ("deepgram", "byok"),
        ("whisper", "local"),
    ]


def test_a_tenant_whisper_server_may_opt_into_platform_fallback(monkeypatch):
    ts = _platform_keys(monkeypatch)

    chain = _chain(
        ts,
        _row(
            "whisper", base_url="http://whisper.lan/v1", allow_platform_fallback=True
        ),
    )

    assert chain[0].credential_source == "local"
    platform = {p.provider_name for p in chain if p.credential_source == "platform"}
    assert platform == {"deepgram", "assemblyai", "yandex_speechkit"}


def test_a_keyed_whisper_row_uses_its_own_address(monkeypatch):
    ts = _platform_keys(monkeypatch)

    chain = _chain(ts, _row("whisper", key="sk-t", base_url="https://stt.example/v1"))

    assert chain[0].provider_name == "whisper"
    assert (chain[0]._api_key, chain[0]._base_url) == ("sk-t", "https://stt.example/v1")
    assert chain[0].credential_source == "byok"


def test_an_unimplemented_provider_row_never_joins_the_chain(monkeypatch):
    ts = _platform_keys(monkeypatch)

    chain = _chain(ts, _row("faster_whisper", key="whatever"))

    assert "faster_whisper" not in [p.provider_name for p in chain]
    with pytest.raises(ValueError):
        ts._build("faster_whisper", "k")


# ---------------------------------------------------------------------------
# HRP-1007: TRANSCRIPTION_PROVIDER_DEFAULT orders the platform part
# ---------------------------------------------------------------------------


def _names(chain):
    return [p.provider_name for p in chain]


def test_empty_default_keeps_the_measured_order(monkeypatch):
    ts = _platform_keys(monkeypatch, default="")

    chain = _chain(ts)

    assert _names(chain) == list(ts._CHAIN_ORDER)
    assert {p.credential_source for p in chain} == {"platform"}


def test_the_default_goes_first_among_platform_providers(monkeypatch):
    ts = _platform_keys(monkeypatch, default="deepgram")

    assert _names(_chain(ts)) == [
        "deepgram",
        "assemblyai",
        "yandex_speechkit",
        "whisper",
    ]


def test_the_tenants_own_key_still_goes_before_the_default(monkeypatch):
    """BYOK first, whatever its place in the measured order — and a keyless
    row is part of the platform part, ordered with the default."""
    ts = _platform_keys(monkeypatch, default="deepgram")

    chain = _chain(
        ts,
        _row("whisper", key="sk-tenant"),
        _row("assemblyai", speakers_expected=3),
    )

    assert _names(chain) == ["whisper", "deepgram", "assemblyai", "yandex_speechkit"]
    assert [p.credential_source for p in chain] == ["byok"] + ["platform"] * 3
    # The keyless row still carries its own settings on the platform key.
    assert chain[2]._speakers_expected == 3


def test_a_default_without_a_platform_key_is_skipped(monkeypatch):
    ts = _platform_keys(monkeypatch, default="deepgram")
    monkeypatch.setattr(ts.settings, "deepgram_api_key", "")

    assert _names(_chain(ts)) == ["assemblyai", "yandex_speechkit", "whisper"]


def test_a_default_the_processor_list_denies_is_skipped(monkeypatch):
    from app.modules.ai import processors

    ts = _platform_keys(monkeypatch, default="deepgram")
    monkeypatch.setattr(
        processors,
        "allowed_processors_sync",
        lambda db, tenant_id: frozenset(processors.PROCESSORS) - {"deepgram"},
    )

    assert _names(_chain(ts)) == ["assemblyai", "yandex_speechkit", "whisper"]


def test_an_unknown_default_refuses_to_start():
    from app.config import Settings
    from app.modules.recruitment.transcription_service import _CHAIN_ORDER
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="TRANSCRIPTION_PROVIDER_DEFAULT"):
        Settings(transcription_provider_default="deepgarm")
    with pytest.raises(ValidationError):
        Settings(transcription_provider_default="faster_whisper")
    for name in _CHAIN_ORDER:
        assert Settings(transcription_provider_default=name)
    normalized = Settings(transcription_provider_default=" Deepgram ")
    assert normalized.transcription_provider_default == "deepgram"
    empty = Settings(transcription_provider_default="")
    assert empty.transcription_provider_default == ""


# ---------------------------------------------------------------------------
# HRP-970: every provider attempt is a row of the AI call log
# ---------------------------------------------------------------------------


class _JournaledProvider(_StubProvider):
    def __init__(self, name, *, model, source="platform", seconds=600.0, **kw):
        super().__init__(name, **kw)
        self.model = model
        self.credential_source = source
        self._seconds = seconds

    async def transcribe(self, audio_path, *, language=None, diarization=True):
        result = await super().transcribe(
            audio_path, language=language, diarization=diarization
        )
        result.duration_seconds = self._seconds
        return result


@pytest.fixture
def journal(monkeypatch):
    from app.core import ai_usage_hooks

    records: list = []

    async def _record(record):
        records.append(record)

    monkeypatch.setattr(ai_usage_hooks, "record_call", _record)
    return records


def _summary(records):
    return [
        (
            r.kind,
            r.provider,
            r.model,
            r.credential_source,
            r.status,
            r.error_code,
            r.audio_seconds,
        )
        for r in records
    ]


@pytest.mark.asyncio
async def test_the_fallback_leaves_one_row_per_attempt(journal):
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    dead = _JournaledProvider("deepgram", model="nova-2", source="byok", refuses=401)
    alive = _JournaledProvider("whisper", model="whisper-1")

    result, _ = await transcribe_with_chain([dead, alive], "x.ogg")

    assert result is not None and result.provider == "whisper"
    assert _summary(journal) == [
        ("transcription", "deepgram", "nova-2", "byok", "error", "http_401", None),
        ("transcription", "whisper", "whisper-1", "platform", "ok", None, 600.0),
    ]
    assert all(r.latency_ms >= 0 and r.input_tokens is None for r in journal)


@pytest.mark.asyncio
async def test_a_provider_that_cannot_take_the_file_is_journaled(journal):
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    await transcribe_with_chain(
        [
            _JournaledProvider("yandex_speechkit", model="general", rejects="-"),
            _JournaledProvider("whisper", model="whisper-1"),
        ],
        "x.ogg",
    )

    assert [(r.provider, r.status, r.error_code) for r in journal] == [
        ("yandex_speechkit", "error", "ValueError"),
        ("whisper", "ok", None),
    ]


@pytest.mark.asyncio
async def test_a_transient_error_is_journaled_before_it_propagates(journal):
    import httpx
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    with pytest.raises(httpx.HTTPStatusError):
        await transcribe_with_chain(
            [_JournaledProvider("assemblyai", model="universal-2", refuses=429)],
            "x.ogg",
        )

    assert [(r.status, r.error_code) for r in journal] == [("error", "http_429")]


@pytest.mark.asyncio
async def test_the_journal_names_the_model_that_actually_ran(journal):
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    provider = AssemblyAIProvider(api_key="k")

    async def _routed(audio_path, *, language=None, diarization=True):
        return _assemblyai_payload_to_result(
            {"speech_model_used": "universal-2", "audio_duration": 61},
            provider="assemblyai",
        )

    provider.transcribe = _routed

    await transcribe_with_chain([provider], "x.ogg")

    assert (journal[0].model, journal[0].audio_seconds) == ("universal-2", 61)
    assert AssemblyAIProvider.model == "universal-3-5-pro"


@pytest.mark.asyncio
async def test_a_broken_journal_never_costs_the_transcript(monkeypatch):
    from app.core import ai_usage_hooks
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    async def _boom(record):
        raise RuntimeError("journal down")

    monkeypatch.setattr(ai_usage_hooks, "record_call", _boom)

    result, err = await transcribe_with_chain(
        [_JournaledProvider("whisper", model="whisper-1")], "x.ogg"
    )
    assert result is not None and err == ""


@pytest.mark.asyncio
async def test_a_guard_refusal_at_call_time_passes_the_turn_on(
    monkeypatch, journal, audio_file
):
    """The tenant's Whisper host started resolving inside the perimeter
    after it was saved: the request-time SSRF layer refuses it, and it will
    refuse it on every retry — a permanent refusal of that row, like a 401,
    not a crash of the chain that leaves the platform providers no turn."""
    from app.core import url_guard
    from app.core.errors import AppError
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    class _Pinned(_RecordingClient):
        async def post(self, *args, **kwargs):
            raise AppError("llm_base_url_not_public", 400)

    monkeypatch.setattr(
        url_guard, "tenant_endpoint_http_client", lambda *a, **k: _Pinned()
    )
    tenant_server = OpenAIWhisperProvider(
        api_key="sk-t", base_url="https://stt.tenant.example/v1"
    )
    tenant_server.credential_source = "byok"
    platform = _JournaledProvider("assemblyai", model="universal-3-5-pro")

    result, err = await transcribe_with_chain([tenant_server, platform], audio_file)

    assert result is not None and result.provider == "assemblyai" and err == ""
    assert [(r.provider, r.status, r.error_code) for r in journal] == [
        ("whisper", "error", "llm_base_url_not_public"),
        ("assemblyai", "ok", None),
    ]


@pytest.mark.asyncio
async def test_a_chain_refused_only_by_the_guard_reports_it(monkeypatch, journal):
    from app.core.errors import AppError
    from app.modules.recruitment.transcription_service import transcribe_with_chain

    class _Guarded(_JournaledProvider):
        async def transcribe(self, audio_path, *, language=None, diarization=True):
            raise AppError("llm_base_url_https_required", 400)

    result, err = await transcribe_with_chain(
        [_Guarded("whisper", model="whisper-1")], "x.ogg"
    )

    assert result is None
    assert "llm_base_url_https_required" in err
