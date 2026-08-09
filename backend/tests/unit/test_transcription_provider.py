"""Unit tests for app.modules.recruitment.transcription_service."""

import pytest
from app.modules.recruitment.transcription_service import (
    AssemblyAIProvider,
    DeepgramProvider,
    FasterWhisperProvider,
    OpenAIWhisperProvider,
    _deepgram_payload_to_result,
    _whisper_payload_to_result,
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


@pytest.mark.asyncio
async def test_assemblyai_provider_is_stub():
    provider = AssemblyAIProvider(api_key="x")
    with pytest.raises(NotImplementedError):
        await provider.transcribe("https://example/audio")


@pytest.mark.asyncio
async def test_faster_whisper_provider_is_stub():
    provider = FasterWhisperProvider(endpoint="https://internal/llm")
    with pytest.raises(NotImplementedError):
        await provider.transcribe("https://example/audio")


def test_provider_names_are_stable():
    assert OpenAIWhisperProvider.provider_name == "whisper"
    assert DeepgramProvider.provider_name == "deepgram"
    assert AssemblyAIProvider.provider_name == "assemblyai"
    assert FasterWhisperProvider.provider_name == "faster_whisper"


def test_whisper_provider_exposes_25mb_cap():
    """The Whisper API rejects payloads above 25 MB; we surface the same
    constant so the worker's pre-flight check (tasks.py) and the streaming
    download (transcription_service.py) stay in sync."""

    assert OpenAIWhisperProvider.WHISPER_MAX_BYTES == 25 * 1024 * 1024


@pytest.mark.asyncio
async def test_whisper_provider_aborts_when_stream_exceeds_25mb(monkeypatch):
    """Stream-time guard: if the audio stream pushes past 25 MB, the
    provider must raise instead of buffering the whole payload to RAM."""

    import httpx

    class _FakeStreamCM:
        def __init__(self, total: int) -> None:
            self._total = total

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, chunk_size=64 * 1024):
            yielded = 0
            block = b"x" * chunk_size
            while yielded < self._total:
                yielded += chunk_size
                yield block

    class _FakeClient:
        def __init__(self, total):
            self._total = total

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url):
            return _FakeStreamCM(self._total)

    over = 26 * 1024 * 1024
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: _FakeClient(over)
    )
    provider = OpenAIWhisperProvider(api_key="x")
    with pytest.raises(ValueError, match="25 MB"):
        await provider.transcribe("https://signed/example")


# ---------------------------------------------------------------------------
# R3b M-3: adversarial httpx mocks (401 / 429 / timeout) for both providers
# ---------------------------------------------------------------------------


def _streaming_client_factory(total_bytes: int = 1024) -> type:
    """Build a fake httpx.AsyncClient class that streams ``total_bytes``
    of dummy audio for the GET (download) leg, then delegates to a
    user-supplied response object for the POST leg.

    Returned class is meant to be installed via
    ``monkeypatch.setattr(httpx, 'AsyncClient', factory(post_response))``.
    """

    class _Stream:
        def __init__(self, total: int) -> None:
            self._total = total

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, chunk_size=64 * 1024):
            block = b"x" * min(chunk_size, self._total)
            yielded = 0
            while yielded < self._total:
                yielded += len(block)
                yield block

    class _Client:
        post_response: object | None = None

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url):
            return _Stream(total_bytes)

        async def post(self, *args, **kwargs):
            resp = type(self).post_response
            if isinstance(resp, BaseException):
                raise resp
            return resp

    return _Client


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


@pytest.mark.asyncio
async def test_whisper_provider_propagates_401_unauthorized(monkeypatch):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = _FakeResponse(401)
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = OpenAIWhisperProvider(api_key="bad")
    with pytest.raises(httpx.HTTPStatusError):
        await provider.transcribe("https://signed/example")


@pytest.mark.asyncio
async def test_whisper_provider_propagates_429_rate_limit(monkeypatch):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = _FakeResponse(429)
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = OpenAIWhisperProvider(api_key="x")
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await provider.transcribe("https://signed/example")
    assert "429" in str(exc.value)


@pytest.mark.asyncio
async def test_whisper_provider_surfaces_request_timeout(monkeypatch):
    import httpx

    Cls = _streaming_client_factory()
    Cls.post_response = httpx.ReadTimeout(
        "timed out", request=httpx.Request("POST", "https://api.test/x")
    )
    monkeypatch.setattr(httpx, "AsyncClient", Cls)

    provider = OpenAIWhisperProvider(api_key="x")
    with pytest.raises(httpx.ReadTimeout):
        await provider.transcribe("https://signed/example")


class _DeepgramFakeClient:
    post_response: object | None = None

    def __init__(self, *args, **kwargs):
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


@pytest.mark.asyncio
async def test_deepgram_provider_propagates_401(monkeypatch):
    import httpx

    _DeepgramFakeClient.post_response = _FakeResponse(401)
    monkeypatch.setattr(httpx, "AsyncClient", _DeepgramFakeClient)

    provider = DeepgramProvider(api_key="bad")
    with pytest.raises(httpx.HTTPStatusError):
        await provider.transcribe("https://signed/example")


@pytest.mark.asyncio
async def test_deepgram_provider_propagates_429(monkeypatch):
    import httpx

    _DeepgramFakeClient.post_response = _FakeResponse(429)
    monkeypatch.setattr(httpx, "AsyncClient", _DeepgramFakeClient)

    provider = DeepgramProvider(api_key="x")
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await provider.transcribe("https://signed/example")
    assert "429" in str(exc.value)


@pytest.mark.asyncio
async def test_deepgram_provider_surfaces_timeout(monkeypatch):
    import httpx

    _DeepgramFakeClient.post_response = httpx.ConnectTimeout(
        "deepgram unreachable",
        request=httpx.Request("POST", "https://api.deepgram.com/v1/listen"),
    )
    monkeypatch.setattr(httpx, "AsyncClient", _DeepgramFakeClient)

    provider = DeepgramProvider(api_key="x")
    with pytest.raises(httpx.ConnectTimeout):
        await provider.transcribe("https://signed/example")


# ---------------------------------------------------------------------------
# BYOK key handling (HRP-506)
# ---------------------------------------------------------------------------


class _FakeSyncResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSyncSession:
    def __init__(self, row):
        self._row = row

    def execute(self, _query):
        return _FakeSyncResult(self._row)


@pytest.mark.asyncio
async def test_byok_transcription_key_is_decrypted(db, tenant, monkeypatch):
    """The stored column is ciphertext — the provider must receive the
    plaintext key, never the blob (HRP-506)."""
    import uuid as _uuid

    from app.core.crypto import encrypt_secret
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(
        transcription_service.settings, "deepgram_api_key", "platform-deepgram"
    )
    row = TranscriptionProviderConfig(
        tenant_id=tenant.id,
        provider="deepgram",
        api_key_encrypted=encrypt_secret("dg-tenant-key"),
        is_active=True,
    )
    db.add(row)
    await db.commit()

    provider = await transcription_service.get_transcription_provider(db, tenant.id)
    assert provider._api_key == "dg-tenant-key"

    sync_provider = transcription_service.get_transcription_provider_sync(
        _FakeSyncSession(row), _uuid.uuid4()
    )
    assert sync_provider._api_key == "dg-tenant-key"


@pytest.mark.asyncio
async def test_row_without_key_falls_back_to_platform_key(db, tenant, monkeypatch):
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(
        transcription_service.settings, "deepgram_api_key", "platform-deepgram"
    )
    db.add(
        TranscriptionProviderConfig(
            tenant_id=tenant.id,
            provider="deepgram",
            api_key_encrypted=None,
            is_active=True,
        )
    )
    await db.commit()

    provider = await transcription_service.get_transcription_provider(db, tenant.id)
    assert provider._api_key == "platform-deepgram"


@pytest.mark.asyncio
async def test_unreadable_key_falls_back_to_platform_key(db, tenant, monkeypatch):
    """A key encrypted under a rotated ENCRYPTION_KEY must degrade to the
    platform credential instead of shipping garbage to the provider."""
    from app.modules.recruitment import transcription_service
    from app.modules.recruitment.models import TranscriptionProviderConfig

    monkeypatch.setattr(
        transcription_service.settings, "deepgram_api_key", "platform-deepgram"
    )
    db.add(
        TranscriptionProviderConfig(
            tenant_id=tenant.id,
            provider="deepgram",
            api_key_encrypted="not-a-valid-ciphertext",
            is_active=True,
        )
    )
    await db.commit()

    provider = await transcription_service.get_transcription_provider(db, tenant.id)
    assert provider._api_key == "platform-deepgram"
