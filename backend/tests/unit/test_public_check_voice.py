"""HRP-947: dictating the description of a public process check - a
recording in, its text out, nothing kept.

The transcription chain is mocked at the module the endpoint calls
(``recruitment.transcription_service``); a live run against Whisper is in
the ticket. Requests come through the test client, whose peer is a trusted
proxy, so ``X-Forwarded-For`` names the visitor as Caddy does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
import uuid

import httpx
import pytest
from app.config import settings
from app.core import ai_usage_hooks
from app.core.redis import redis_client
from app.modules.public_check import router, schemas, service, voice
from app.modules.public_check.models import PublicCheck
from app.modules.recruitment import transcription_service
from app.modules.recruitment.transcription_service import (
    TranscriptionResult,
    TranscriptSegment,
)
from app.modules.work.models import WorkContainer
from sqlalchemy import select

URL = "/api/public-check/transcribe"
CHECKS = "/api/public-check/checks"
VISITOR = {"X-Forwarded-For": "203.0.113.7"}
AUDIO = b"\x1aE\xdf\xa3 not really opus " * 64
MEASURE = voice._measure  # before the fixture swaps it


def _files(data: bytes = AUDIO, kind: str = "audio/webm;codecs=opus", name="r.webm"):
    return {"audio": (name, data, kind)}


class _Chain:
    """The provider chain: records every call and answers ``result`` (or
    raises ``error``). The recording must exist while it is transcribed."""

    def __init__(self, result=None, error: Exception | None = None, last="", delay=0.0):
        self.result, self.error, self.last, self.delay = result, error, last, delay
        self.calls: list[dict] = []

    async def __call__(self, providers, audio_path, *, language=None):
        with open(audio_path, "rb") as handle:
            self.calls.append(
                {
                    "providers": providers,
                    "path": audio_path,
                    "language": language,
                    "data": handle.read(),
                    # The AI call journal's view of who is calling.
                    "context": ai_usage_hooks.current(),
                }
            )
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result, self.last


def _result(text="We close the month.", language="english", duration=42.0, **kw):
    return TranscriptionResult(
        full_text=text, language=language, duration_seconds=duration, **kw
    )


@pytest.fixture(autouse=True)
def _voice(monkeypatch, tmp_path):
    """The service on, its own sandbox, no throttle, no daily cap, every
    temp file of the request under ``tmp_path``, one provider configured,
    every recording measured at 42 seconds (CI has no ffmpeg)."""
    monkeypatch.setattr(settings, "public_check_enabled", True)
    monkeypatch.setattr(settings, "public_check_paused", False)
    monkeypatch.setattr(settings, "public_check_voice_daily_minutes", 0)
    monkeypatch.setattr(service, "SANDBOX_SLUG", f"pc_voice_{uuid.uuid4().hex[:10]}")
    monkeypatch.setattr(router.limiter, "enabled", False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(voice, "_measure", lambda _path: 42.0)
    monkeypatch.setattr(
        transcription_service,
        "get_transcription_chain_sync",
        lambda _session, _tenant_id: ["whisper"],
    )


@pytest.fixture
def chain(monkeypatch):
    def _install(**answer) -> _Chain:
        fake = _Chain(**answer)
        monkeypatch.setattr(transcription_service, "transcribe_with_chain", fake)
        return fake

    return _install


@pytest.fixture
def spent(monkeypatch):
    """Every ``spend_daily`` call, passed through to the real counter."""
    calls: list[tuple] = []
    real = service.spend_daily

    async def _spy(counter, limit, amount=1):
        calls.append((counter, limit, amount))
        await real(counter, limit, amount)

    monkeypatch.setattr(service, "spend_daily", _spy)
    return calls


@pytest.fixture
async def clean_minutes():
    async def _drop():
        async with redis_client() as client:
            keys = await client.keys(f"public_check:daily:{voice.MINUTES}:*")
            if keys:
                await client.delete(*keys)

    await _drop()
    yield
    await _drop()


class TestTranscribe:
    async def test_the_text_and_language_come_back(self, client, chain, tmp_path):
        fake = chain(result=_result())
        resp = await client.post(URL, files=_files())
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"text": "We close the month.", "language": "english"}
        (call,) = fake.calls
        # The sandbox's chain, the language left to the provider, the
        # recording whole under the extension of its type.
        assert call["providers"] == ["whisper"]
        assert call["language"] is None
        assert call["data"] == AUDIO
        assert call["path"].endswith(".webm")
        assert list(tmp_path.iterdir()) == []  # nothing kept

    @pytest.mark.parametrize(
        ("kind", "suffix"),
        [
            ("audio/mp4", ".mp4"),  # Safari
            ("audio/ogg;codecs=opus", ".ogg"),  # Firefox
            ("audio/wav", ".wav"),
            ("audio/mpeg", ".mp3"),
        ],
    )
    async def test_every_recorder_container_is_taken(self, client, chain, kind, suffix):
        fake = chain(result=_result())
        resp = await client.post(URL, files=_files(kind=kind, name="blob"))
        assert resp.status_code == 200, resp.text
        assert fake.calls[0]["path"].endswith(suffix)

    async def test_the_sandbox_chain_is_asked(self, client, chain, db, monkeypatch):
        chain(result=_result())
        asked: list = []

        def _chain(_session, tenant_id):
            asked.append(tenant_id)
            return ["whisper"]

        monkeypatch.setattr(
            transcription_service, "get_transcription_chain_sync", _chain
        )
        assert (await client.post(URL, files=_files())).status_code == 200
        sandbox_id, _ = await service.ensure_sandbox(db)
        assert asked == [sandbox_id]

    async def test_the_provider_calls_are_filed_under_the_check(
        self, client, chain, db
    ):
        """Wave 13's ASR journal reads the call context: the recording's
        calls belong to the sandbox and the public check, not to nobody."""
        fake = chain(result=_result())
        assert (await client.post(URL, files=_files())).status_code == 200
        sandbox_id, _ = await service.ensure_sandbox(db)
        context = fake.calls[0]["context"]
        assert context.tenant_id == sandbox_id
        assert context.action == "public_check.transcribe"
        assert context.work_unit_id is not None
        assert ai_usage_hooks.current() is None  # unbound after the call

    async def test_silence_is_an_empty_text(self, client, chain):
        chain(result=_result(text="  ", language=None))
        resp = await client.post(URL, files=_files())
        assert resp.json() == {"text": "", "language": None}


class TestRefusals:
    async def test_switched_off_is_the_404_of_the_service(
        self, client, chain, monkeypatch
    ):
        fake = chain(result=_result())
        monkeypatch.setattr(settings, "public_check_enabled", False)
        resp = await client.post(URL, files=_files())
        assert resp.status_code == 404
        assert resp.json()["code"] == "public_check_not_found"
        assert fake.calls == []

    async def test_the_pause_refuses_before_any_work(self, client, chain, monkeypatch):
        fake = chain(result=_result())
        monkeypatch.setattr(router.limiter, "enabled", True)
        monkeypatch.setattr(settings, "public_check_voice_rate_limit", "1/hour")
        router.limiter.reset()

        def _no_chain(*_a):
            raise AssertionError("the pause must refuse before the chain")

        monkeypatch.setattr(
            transcription_service, "get_transcription_chain_sync", _no_chain
        )
        monkeypatch.setattr(settings, "public_check_paused", True)
        for _ in range(2):
            resp = await client.post(URL, files=_files(), headers=VISITOR)
            assert resp.status_code == 429
            assert resp.json()["code"] == "public_check_daily_limit"
            assert int(resp.headers["Retry-After"]) >= 1
        assert fake.calls == []
        # Paused requests spent nothing of the visitor's throttle.
        monkeypatch.setattr(settings, "public_check_paused", False)
        monkeypatch.setattr(
            transcription_service,
            "get_transcription_chain_sync",
            lambda *_a: ["whisper"],
        )
        resp = await client.post(URL, files=_files(), headers=VISITOR)
        assert resp.status_code == 200, resp.text
        router.limiter.reset()

    @pytest.mark.parametrize(
        ("body", "kind"),
        [
            ({"files": _files(kind="text/plain")}, "a part of another type"),
            ({"files": _files(kind="video/webm")}, "video"),
            (
                {"files": {"recording": ("r.webm", AUDIO, "audio/webm")}},
                "no audio field",
            ),
            ({"json": {"audio": "AAAA"}}, "not multipart"),
            ({"data": {"audio": "x"}, "files": _files()}, "an extra field"),
        ],
    )
    async def test_anything_but_one_audio_part_is_415(
        self, client, chain, tmp_path, body, kind
    ):
        fake = chain(result=_result())
        resp = await client.post(URL, **body)
        assert resp.status_code == 415, kind
        assert resp.json()["code"] == "public_check_voice_unsupported"
        assert fake.calls == []
        assert list(tmp_path.iterdir()) == []

    async def test_a_declared_body_over_the_ceiling_is_413_unread(
        self, client, chain, monkeypatch
    ):
        fake = chain(result=_result())
        monkeypatch.setattr(voice, "MAX_BODY_BYTES", 1024)

        def _no_chain(*_a):
            raise AssertionError("a declared oversize body is refused first")

        monkeypatch.setattr(
            transcription_service, "get_transcription_chain_sync", _no_chain
        )
        resp = await client.post(URL, files=_files(data=b"x" * 2048))
        assert resp.status_code == 413
        assert resp.json()["code"] == "public_check_voice_too_large"
        assert fake.calls == []

    async def test_an_undeclared_body_stops_at_the_ceiling(
        self, client, chain, monkeypatch, tmp_path
    ):
        """Chunked, no Content-Length: the stream is cut the moment it
        passes the ceiling, the rest is never pulled."""
        fake = chain(result=_result())
        monkeypatch.setattr(voice, "MAX_BODY_BYTES", 4096)
        boundary = "voiceboundary"
        pulled: list[int] = []

        async def body():
            yield (
                f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; '
                f'filename="r.webm"\r\nContent-Type: audio/webm\r\n\r\n'
            ).encode()
            for i in range(100):
                pulled.append(i)
                yield b"x" * 1024
            yield f"\r\n--{boundary}--\r\n".encode()

        resp = await client.post(
            URL,
            content=body(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        assert resp.status_code == 413
        assert resp.json()["code"] == "public_check_voice_too_large"
        assert len(pulled) < 10  # the body was not read to its end
        assert fake.calls == []
        assert list(tmp_path.iterdir()) == []

    async def test_every_provider_refusing_is_503(self, client, chain, tmp_path):
        fake = chain(result=None, last="whisper refused the request (HTTP 401)")
        resp = await client.post(URL, files=_files())
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_voice_unavailable"
        assert len(fake.calls) == 1
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize(
        "error",
        [
            httpx.HTTPStatusError(
                "busy",
                request=httpx.Request("POST", "https://api.openai.com"),
                response=httpx.Response(503),
            ),
            httpx.ReadTimeout("slow"),
        ],
    )
    async def test_a_transient_error_is_the_same_503_without_retry(
        self, client, chain, tmp_path, error
    ):
        fake = chain(error=error)
        resp = await client.post(URL, files=_files())
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_voice_unavailable"
        assert len(fake.calls) == 1
        assert list(tmp_path.iterdir()) == []

    async def test_a_hanging_provider_is_cut_off_with_the_503(
        self, client, chain, monkeypatch, tmp_path
    ):
        fake = chain(result=_result(), delay=5)
        monkeypatch.setattr(voice, "TRANSCRIBE_TIMEOUT_S", 0.05)
        resp = await asyncio.wait_for(client.post(URL, files=_files()), 3)
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_voice_unavailable"
        assert len(fake.calls) == 1
        assert list(tmp_path.iterdir()) == []

    async def test_a_malformed_multipart_body_is_415(self, client, chain, tmp_path):
        fake = chain(result=_result())
        resp = await client.post(
            URL,
            content=b"--other\r\nnot a part at all",
            headers={"Content-Type": "multipart/form-data; boundary=voiceboundary"},
        )
        assert resp.status_code == 415
        assert resp.json()["code"] == "public_check_voice_unsupported"
        assert fake.calls == []
        assert list(tmp_path.iterdir()) == []

    async def test_a_client_gone_mid_upload_is_a_quiet_400(
        self, client, chain, caplog, tmp_path
    ):
        """No traceback for a visitor who closed the tab mid-upload."""
        from app.main import app

        fake = chain(result=_result())
        messages = [
            {
                "type": "http.request",
                "body": (
                    b'--b\r\nContent-Disposition: form-data; name="audio"; '
                    b'filename="r"\r\nContent-Type: audio/webm\r\n\r\nxx'
                ),
                "more_body": True,
            },
        ]

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": URL,
            "raw_path": URL.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"test"),
                (b"content-type", b"multipart/form-data; boundary=b"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
        }
        with caplog.at_level(logging.INFO):
            await app(scope, receive, send)
        start = next(m for m in sent if m["type"] == "http.response.start")
        body = b"".join(
            m.get("body", b"") for m in sent if m["type"] == "http.response.body"
        )
        assert start["status"] == 400
        assert json.loads(body)["code"] == "public_check_voice_incomplete"
        assert fake.calls == []
        assert not [
            r for r in caplog.records if r.exc_info or r.levelno >= logging.ERROR
        ]
        assert list(tmp_path.iterdir()) == []

    async def test_no_provider_is_503_before_the_body(self, client, chain, monkeypatch):
        fake = chain(result=_result())
        monkeypatch.setattr(
            transcription_service, "get_transcription_chain_sync", lambda *_a: []
        )
        resp = await client.post(URL, files=_files())
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_voice_unavailable"
        assert fake.calls == []


class TestThrottle:
    async def test_recordings_have_a_bucket_of_their_own(
        self, client, chain, monkeypatch
    ):
        chain(result=_result())
        monkeypatch.setattr(router.limiter, "enabled", True)
        monkeypatch.setattr(settings, "public_check_voice_rate_limit", "1/hour")
        monkeypatch.setattr(settings, "public_check_rate_limit", "1/hour")
        monkeypatch.setattr(settings, "public_check_turnstile_secret", "")
        monkeypatch.setattr(settings, "public_check_daily_limit", 0)
        router.limiter.reset()
        try:
            assert (
                await client.post(URL, files=_files(), headers=VISITOR)
            ).status_code == 200
            refused = await client.post(URL, files=_files(), headers=VISITOR)
            assert refused.status_code == 429
            assert refused.json()["code"] == "public_check_rate_limited"
            assert 1 <= int(refused.headers["Retry-After"]) <= 3600
            # The visitor's recordings are spent, their check is not.
            check = await client.post(
                CHECKS,
                json={
                    "description": f"We answer requests and file returns. {uuid.uuid4()}"
                },
                headers=VISITOR,
            )
            assert check.status_code == 202, check.text
            # Another visitor behind the same proxy records on.
            other = {"X-Forwarded-For": "198.51.100.9"}
            assert (
                await client.post(URL, files=_files(), headers=other)
            ).status_code == 200
        finally:
            router.limiter.reset()


async def _counter() -> int:
    async with redis_client() as client:
        return int(await client.get(service.daily_key(voice.MINUTES)) or 0)


class TestDailyMinutes:
    async def test_no_cap_reads_no_counter(self, client, chain, spent, monkeypatch):
        chain(result=_result(duration=61))

        def _no_redis():
            raise AssertionError("no cap, no Redis")

        monkeypatch.setattr(service, "redis_client", _no_redis)
        assert (await client.post(URL, files=_files())).status_code == 200
        assert spent == [(voice.MINUTES, 0, voice.RESERVED)]

    @pytest.mark.parametrize(
        ("result", "minutes"),
        [
            (_result(duration=0.4), 1),
            (_result(duration=60.0), 1),
            (_result(duration=61.0), 2),
            # No duration: the last segment's end, then the measured length.
            (
                _result(
                    duration=None,
                    segments=[TranscriptSegment("speaker_0", 0.0, 70.0, "x")],
                ),
                2,
            ),
            (_result(duration=None), 1),
        ],
    )
    async def test_the_reservation_settles_at_whole_minutes(
        self, client, chain, spent, clean_minutes, monkeypatch, result, minutes
    ):
        monkeypatch.setattr(settings, "public_check_voice_daily_minutes", 100)
        chain(result=result)
        assert (await client.post(URL, files=_files())).status_code == 200
        assert spent == [(voice.MINUTES, 100, voice.RESERVED)]
        assert await _counter() == minutes

    async def test_spent_minutes_refuse_before_transcription(
        self, client, chain, clean_minutes, monkeypatch
    ):
        monkeypatch.setattr(settings, "public_check_voice_daily_minutes", 3)
        fake = chain(result=_result(duration=150))  # 3 minutes
        assert (await client.post(URL, files=_files())).status_code == 200
        refused = await client.post(URL, files=_files())
        assert refused.status_code == 429
        assert refused.json()["code"] == "public_check_daily_limit"
        assert int(refused.headers["Retry-After"]) >= 1
        assert len(fake.calls) == 1

    async def test_parallel_recordings_cannot_pass_one_read(
        self, client, chain, clean_minutes, monkeypatch
    ):
        """Room for one recording: two at once, the second is refused before
        the provider even if the first is still being transcribed."""
        monkeypatch.setattr(
            settings, "public_check_voice_daily_minutes", voice.RESERVED
        )
        fake = chain(result=_result(duration=30), delay=0.3)
        first, second = await asyncio.gather(
            client.post(URL, files=_files()), client.post(URL, files=_files())
        )
        assert sorted([first.status_code, second.status_code]) == [200, 429]
        assert len(fake.calls) == 1

    async def test_a_refusal_before_the_provider_gives_the_minutes_back(
        self, client, chain, clean_minutes, monkeypatch
    ):
        monkeypatch.setattr(settings, "public_check_voice_daily_minutes", 100)
        fake = chain(result=_result())
        resp = await client.post(URL, files=_files(kind="text/plain"))
        assert resp.status_code == 415
        assert fake.calls == []
        assert await _counter() == 0

    @pytest.mark.parametrize(
        "answer",
        [{"error": httpx.ReadTimeout("slow")}, {"result": None, "last": "refused"}],
        ids=["timeout", "refused"],
    )
    async def test_a_failed_provider_call_still_counts_the_recording(
        self, client, chain, clean_minutes, monkeypatch, answer
    ):
        monkeypatch.setattr(settings, "public_check_voice_daily_minutes", 100)
        monkeypatch.setattr(voice, "_measure", lambda _path: 100.0)
        chain(**answer)
        assert (await client.post(URL, files=_files())).status_code == 503
        assert await _counter() == 2  # the measured 100 seconds

    async def test_an_unreachable_redis_refuses_recordings(
        self, client, chain, monkeypatch
    ):
        monkeypatch.setattr(settings, "public_check_voice_daily_minutes", 1)
        fake = chain(result=_result())

        class _Down:
            async def __aenter__(self):
                raise ConnectionRefusedError

            async def __aexit__(self, *_exc):
                return False

        monkeypatch.setattr(service, "redis_client", _Down)
        resp = await client.post(URL, files=_files())
        assert resp.status_code == 503
        assert resp.json()["code"] == "public_check_unavailable"
        assert fake.calls == []


class TestLength:
    """The server measures the recording before any provider hears it."""

    @staticmethod
    def _ffmpeg(monkeypatch, *, stdout="", returncode=0, error=None):
        def _run(args, **_kwargs):
            assert args[0] == "ffmpeg"
            if error:
                raise error
            return subprocess.CompletedProcess(args, returncode, stdout, "")

        monkeypatch.setattr(voice.subprocess, "run", _run)

    def test_the_decoded_length_is_read(self, monkeypatch):
        self._ffmpeg(monkeypatch, stdout="out_time_us=1000\nout_time_us=7307000\n")
        assert MEASURE("r.webm") == 7.307

    @pytest.mark.parametrize(
        ("kw", "status", "code"),
        [
            ({"stdout": "out_time_us=200000000\n"}, 413, "public_check_voice_too_long"),
            ({"returncode": 183}, 415, "public_check_voice_unsupported"),
            ({"stdout": "out_time_us=N/A\n"}, 415, "public_check_voice_unsupported"),
            ({"error": FileNotFoundError()}, 503, "public_check_voice_unavailable"),
        ],
        ids=["too-long", "unreadable", "no-length", "no-ffmpeg"],
    )
    def test_a_recording_the_server_cannot_cap_is_refused(
        self, monkeypatch, kw, status, code
    ):
        self._ffmpeg(monkeypatch, **kw)
        with pytest.raises(service.AppError) as refused:
            MEASURE("r.webm")
        assert (refused.value.status_code, refused.value.code) == (status, code)

    async def test_too_long_never_reaches_the_provider(
        self, client, chain, clean_minutes, monkeypatch
    ):
        monkeypatch.setattr(settings, "public_check_voice_daily_minutes", 100)
        # The real ``_measure`` over a fake ffmpeg.
        monkeypatch.setattr(voice, "_measure", MEASURE)
        self._ffmpeg(monkeypatch, stdout="out_time_us=600000000\n")
        fake = chain(result=_result())
        resp = await client.post(URL, files=_files())
        assert resp.status_code == 413
        assert resp.json()["code"] == "public_check_voice_too_long"
        assert fake.calls == []
        assert await _counter() == 0


class TestDictatedFlag:
    def test_the_flag_tells_the_model_and_its_absence_changes_nothing(self):
        answers = {"industry": "Retail", "frequency": "weekly"}
        typed = schemas.CheckCreate(
            description="We count the stock every week.", answers=answers
        )
        dictated = schemas.CheckCreate(
            description="We count the stock every week.", answers=answers, dictated=True
        )
        # Byte for byte the text before HRP-947.
        assert service.process_text(typed) == (
            "We count the stock every week.\n\nIndustry: Retail\nThe process runs every week."
        )
        assert service.process_text(dictated) == (
            f"{service.DICTATED_NOTE}\n\n{service.process_text(typed)}"
        )
        bare = schemas.CheckCreate(description="We count the stock in the store.")
        assert service.process_text(bare) == "We count the stock in the store."

    async def test_a_dictated_check_reaches_the_model_marked(self, client, db):
        text = f"We answer requests and file returns. {uuid.uuid4()}"
        resp = await client.post(CHECKS, json={"description": text, "dictated": True})
        assert resp.status_code == 202, resp.text
        check = await db.scalar(
            select(PublicCheck).where(
                PublicCheck.token_hash == service.hash_token(resp.json()["token"])
            )
        )
        container = await db.get(WorkContainer, check.container_id)
        # The model reads the note; the visitor's own text is kept as typed.
        assert container.description == f"{service.DICTATED_NOTE}\n\n{text}"
        assert check.description == text
        assert container.title == text


def test_the_recording_ceiling_holds_the_longest_recording():
    """Three minutes at 128 kbit/s - the browsers' default - fit the body
    ceiling with room: the page's timer, not the server, ends a recording."""
    assert voice.MAX_SECONDS * 128_000 / 8 < voice.MAX_BODY_BYTES / 2
