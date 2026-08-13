"""Tests for core infrastructure modules and services that depend on external services.

Covers: core/email, core/s3, core/events, notification/service, storage/service,
        ai/service, ai/llm_client.
All external dependencies (SMTP, S3/boto3, LLM APIs) are mocked.
"""

import json
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# core/email.py
# ---------------------------------------------------------------------------


class TestSendEmail:
    def test_send_email_smtp_not_configured(self):
        from app.core.email import send_email

        with patch("app.core.email.settings") as mock_settings:
            mock_settings.smtp_host = ""
            result = send_email("user@example.com", "Subject", "<p>body</p>")
        assert result == (False, None)

    def test_send_email_success_no_auth(self):
        from app.core.email import send_email

        mock_server = MagicMock()
        with (
            patch("app.core.email.settings") as mock_settings,
            patch("app.core.email.smtplib.SMTP") as mock_smtp_cls,
        ):
            mock_settings.resend_api_key = ""
            mock_settings.smtp_host = "mail.test.com"
            mock_settings.smtp_port = 25
            mock_settings.smtp_user = ""
            mock_settings.smtp_password = ""
            mock_settings.email_from = "noreply@test.com"
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = send_email("user@example.com", "Hello", "<p>world</p>")

        ok, msg_id = result
        assert ok is True
        assert msg_id is not None
        mock_server.sendmail.assert_called_once()
        mock_server.starttls.assert_not_called()
        mock_server.login.assert_not_called()

    def test_send_email_success_with_auth(self):
        from app.core.email import send_email

        mock_server = MagicMock()
        with (
            patch("app.core.email.settings") as mock_settings,
            patch("app.core.email.smtplib.SMTP") as mock_smtp_cls,
        ):
            mock_settings.resend_api_key = ""
            mock_settings.smtp_host = "mail.test.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_user = "sender"
            mock_settings.smtp_password = "secret"
            mock_settings.email_from = "noreply@test.com"
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = send_email("user@example.com", "Hello", "<p>auth</p>")

        ok, msg_id = result
        assert ok is True
        assert msg_id is not None
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender", "secret")

    def test_send_email_exception_returns_false(self):
        from app.core.email import send_email

        with (
            patch("app.core.email.settings") as mock_settings,
            patch("app.core.email.smtplib.SMTP", side_effect=ConnectionError("fail")),
        ):
            mock_settings.smtp_host = "mail.test.com"
            mock_settings.smtp_port = 587
            mock_settings.email_from = "noreply@test.com"

            result = send_email("user@example.com", "Hello", "<p>err</p>")

        assert result == (False, None)


# ---------------------------------------------------------------------------
# core/s3.py
# ---------------------------------------------------------------------------


class TestS3Client:
    def test_get_s3_client_not_configured(self):
        from app.core.s3 import get_s3_client

        with patch("app.core.s3.settings") as mock_settings:
            mock_settings.s3_endpoint = ""
            assert get_s3_client() is None

    def test_get_s3_client_configured(self):
        from app.core.s3 import get_s3_client

        mock_client = MagicMock()
        with (
            patch("app.core.s3.settings") as mock_settings,
            patch("app.core.s3.boto3.client", return_value=mock_client) as mock_boto,
        ):
            mock_settings.s3_endpoint = "http://minio:9000"
            mock_settings.s3_access_key = "key"
            mock_settings.s3_secret_key = "secret"

            client = get_s3_client()

        assert client is mock_client
        # HRP-14: presigned URLs must be SigV4 so MinIO / modern S3 regions
        # accept them.
        assert mock_boto.call_count == 1
        args, kwargs = mock_boto.call_args
        assert args == ("s3",)
        assert kwargs["endpoint_url"] == "http://minio:9000"
        assert kwargs["aws_access_key_id"] == "key"
        assert kwargs["aws_secret_access_key"] == "secret"
        assert kwargs["config"].signature_version == "s3v4"


class TestS3Upload:
    def test_upload_file_no_client(self):
        from app.core.s3 import upload_file

        with patch("app.core.s3.get_s3_client", return_value=None):
            result = upload_file(b"data", "path/file.txt", "text/plain")
        assert result is None

    def test_upload_file_success(self):
        from app.core.s3 import upload_file

        mock_client = MagicMock()
        with (
            patch("app.core.s3.get_s3_client", return_value=mock_client),
            patch("app.core.s3.settings") as mock_settings,
        ):
            mock_settings.s3_endpoint = "http://minio:9000"
            mock_settings.s3_bucket = "hrpulsar"

            result = upload_file(b"filedata", "tenant/file.pdf", "application/pdf")

        assert result == "http://minio:9000/hrpulsar/tenant/file.pdf"
        mock_client.put_object.assert_called_once_with(
            Bucket="hrpulsar",
            Key="tenant/file.pdf",
            Body=b"filedata",
            ContentType="application/pdf",
        )

    def test_upload_file_client_error(self, caplog):
        from app.core.s3 import upload_file

        mock_client = MagicMock()
        mock_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "fail"}}, "PutObject"
        )
        with (
            patch("app.core.s3.get_s3_client", return_value=mock_client),
            caplog.at_level(logging.CRITICAL, logger="app.core.s3"),
        ):
            result = upload_file(b"data", "path.txt", "text/plain")
        assert result is None


class TestS3Delete:
    def test_delete_file_no_client(self):
        from app.core.s3 import delete_file

        with patch("app.core.s3.get_s3_client", return_value=None):
            assert delete_file("path.txt") is False

    def test_delete_file_success(self):
        from app.core.s3 import delete_file

        mock_client = MagicMock()
        with (
            patch("app.core.s3.get_s3_client", return_value=mock_client),
            patch("app.core.s3.settings") as mock_settings,
        ):
            mock_settings.s3_bucket = "hrpulsar"
            assert delete_file("tenant/file.pdf") is True

        mock_client.delete_object.assert_called_once_with(
            Bucket="hrpulsar", Key="tenant/file.pdf"
        )

    def test_delete_file_client_error(self, caplog):
        from app.core.s3 import delete_file

        mock_client = MagicMock()
        mock_client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "fail"}}, "DeleteObject"
        )
        with (
            patch("app.core.s3.get_s3_client", return_value=mock_client),
            patch("app.core.s3.settings") as mock_settings,
            caplog.at_level(logging.CRITICAL, logger="app.core.s3"),
        ):
            mock_settings.s3_bucket = "hrpulsar"
            assert delete_file("path.txt") is False


class TestS3PresignedUrl:
    def test_presigned_url_no_client(self):
        from app.core.s3 import get_presigned_url

        with patch("app.core.s3.get_s3_client", return_value=None):
            assert get_presigned_url("path.txt") is None

    def test_presigned_url_success(self):
        from app.core.s3 import get_presigned_url

        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://signed-url"
        with (
            patch("app.core.s3.get_s3_client", return_value=mock_client),
            patch("app.core.s3.settings") as mock_settings,
        ):
            mock_settings.s3_bucket = "hrpulsar"
            # Empty public endpoint keeps the presign path on the patched
            # get_s3_client seam (HRP-412).
            mock_settings.s3_public_endpoint = ""
            result = get_presigned_url("tenant/file.pdf", expires_in=600)

        assert result == "https://signed-url"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "hrpulsar", "Key": "tenant/file.pdf"},
            ExpiresIn=600,
        )

    def test_presigned_url_client_error(self, caplog):
        from app.core.s3 import get_presigned_url

        mock_client = MagicMock()
        mock_client.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "fail"}}, "GetObject"
        )
        with (
            patch("app.core.s3.get_s3_client", return_value=mock_client),
            patch("app.core.s3.settings") as mock_settings,
            caplog.at_level(logging.CRITICAL, logger="app.core.s3"),
        ):
            mock_settings.s3_bucket = "hrpulsar"
            # Empty public endpoint keeps the presign path on the patched
            # get_s3_client seam (HRP-412).
            mock_settings.s3_public_endpoint = ""
            assert get_presigned_url("path.txt") is None


# ---------------------------------------------------------------------------
# core/events.py
# ---------------------------------------------------------------------------


class TestEventBus:
    async def test_subscribe_and_publish(self):
        from app.core import events

        # Reset handlers to avoid cross-test pollution
        original = events._handlers.copy()
        events._handlers.clear()
        try:
            received = []

            async def handler(data):
                received.append(data)

            events.subscribe("test.event", handler)
            await events.publish("test.event", {"key": "value"})

            assert len(received) == 1
            assert received[0] == {"key": "value"}
        finally:
            events._handlers.clear()
            events._handlers.update(original)

    async def test_publish_no_handlers(self):
        from app.core import events

        original = events._handlers.copy()
        events._handlers.clear()
        try:
            # Should not raise
            await events.publish("no.handlers", {"data": 1})
        finally:
            events._handlers.clear()
            events._handlers.update(original)

    async def test_publish_handler_exception_does_not_propagate(self, caplog):
        import logging

        from app.core import events

        original = events._handlers.copy()
        events._handlers.clear()
        try:
            called_after = []

            async def bad_handler(data):
                raise RuntimeError("boom")

            async def good_handler(data):
                called_after.append(data)

            events.subscribe("err.event", bad_handler)
            events.subscribe("err.event", good_handler)

            with caplog.at_level(logging.CRITICAL, logger="app.core.events"):
                # Should not raise despite bad_handler
                await events.publish("err.event", {"x": 1})
            assert len(called_after) == 1
        finally:
            events._handlers.clear()
            events._handlers.update(original)

    async def test_multiple_subscribers(self):
        from app.core import events

        original = events._handlers.copy()
        events._handlers.clear()
        try:
            calls_a, calls_b = [], []

            async def handler_a(data):
                calls_a.append(data)

            async def handler_b(data):
                calls_b.append(data)

            events.subscribe("multi", handler_a)
            events.subscribe("multi", handler_b)

            await events.publish("multi", {"val": 42})

            assert len(calls_a) == 1
            assert len(calls_b) == 1
        finally:
            events._handlers.clear()
            events._handlers.update(original)


# ---------------------------------------------------------------------------
# notification/service.py
# ---------------------------------------------------------------------------


class TestNotificationService:
    async def test_send_notification_template_not_found(
        self, db: AsyncSession, tenant, user
    ):
        from app.modules.notification import service

        with patch.object(service, "enqueue_email") as mock_enq:
            await service.send_notification(
                db,
                tenant_id=tenant.id,
                template_code="nonexistent_template",
                recipient_id=user.id,
                recipient_email=user.email,
                context={"name": "Test"},
            )

        mock_enq.assert_not_called()

    async def test_send_notification_success(self, db: AsyncSession, tenant, user):
        from app.modules.notification import service
        from app.modules.notification.models import NotificationTemplate

        tpl = NotificationTemplate(
            code=f"test_tpl_{uuid.uuid4().hex[:6]}",
            subject_template="Hello {{ name }}",
            body_template="<p>Dear {{ name }}, welcome!</p>",
        )
        db.add(tpl)
        await db.commit()
        await db.refresh(tpl)

        with patch.object(service, "enqueue_email") as mock_enq:
            await service.send_notification(
                db,
                tenant_id=tenant.id,
                template_code=tpl.code,
                recipient_id=user.id,
                recipient_email=user.email,
                context={"name": "Alice"},
            )

        mock_enq.assert_called_once()
        call_args = mock_enq.call_args
        assert call_args[0][0] == user.email
        assert call_args[0][1] == "Hello Alice"
        # HRP-568: the fragment is delivered inside the branded layout.
        assert "<p>Dear Alice, welcome!</p>" in call_args[0][2]

        from app.modules.notification.models import Notification
        from sqlalchemy import select

        result = await db.execute(
            select(Notification).where(
                Notification.template_id == tpl.id,
                Notification.recipient_id == user.id,
            )
        )
        notif = result.scalar_one()
        # Optimistically marked sent: actual delivery tracked via Resend
        # webhook → EmailLog after the Celery task executes.
        assert notif.status == "sent"
        assert notif.sent_at is not None

    async def test_send_notification_email_disabled_no_dispatch(
        self, db: AsyncSession, tenant, user
    ):
        """Email-disabled preference suppresses enqueue_email; in-app still recorded."""
        from app.modules.notification import service
        from app.modules.notification.models import (
            NotificationPreference,
            NotificationTemplate,
        )

        tpl = NotificationTemplate(
            code=f"off_tpl_{uuid.uuid4().hex[:6]}",
            subject_template="Subject",
            body_template="<p>Body</p>",
        )
        db.add(tpl)
        db.add(
            NotificationPreference(
                user_id=user.id,
                event_type="general",
                channel="email",
                enabled=False,
            )
        )
        await db.commit()
        await db.refresh(tpl)

        with patch.object(service, "enqueue_email") as mock_enq:
            await service.send_notification(
                db,
                tenant_id=tenant.id,
                template_code=tpl.code,
                recipient_id=user.id,
                recipient_email=user.email,
                context={},
            )

        mock_enq.assert_not_called()

        from app.modules.notification.models import Notification
        from sqlalchemy import select

        result = await db.execute(
            select(Notification).where(Notification.template_id == tpl.id)
        )
        notif = result.scalar_one()
        assert notif.status == "sent"  # in-app record still considered sent


# ---------------------------------------------------------------------------
# storage/service.py
# ---------------------------------------------------------------------------


class TestStorageService:
    async def test_upload_file(self, db: AsyncSession, tenant, user):
        from app.modules.storage import service as storage_svc

        mock_upload = MagicMock(
            filename="report.pdf",
            content_type="application/pdf",
            read=AsyncMock(return_value=b"PDF-CONTENT"),
        )

        with patch.object(
            storage_svc, "upload_file", return_value="http://s3/hrpulsar/path"
        ) as mock_s3:
            result = await storage_svc.upload(
                db, tenant.id, user.id, mock_upload, entity_type="assessment"
            )

        assert result["original_name"] == "report.pdf"
        assert result["mime_type"] == "application/pdf"
        assert result["size"] == len(b"PDF-CONTENT")
        assert result["url"] == "http://s3/hrpulsar/path"
        mock_s3.assert_called_once()

    async def test_upload_unknown_type_rejected(self, db: AsyncSession, tenant, user):
        """P0-4: generic ``application/octet-stream`` (unknown binary) is no
        longer accepted — the storage allowlist rejects it rather than
        persisting an untyped ``.bin`` blob the presigned URL would serve back.
        """
        from app.modules.storage import service as storage_svc

        mock_upload = MagicMock(
            filename="noext",
            content_type="application/octet-stream",
            read=AsyncMock(return_value=b"data"),
        )

        with (
            patch.object(storage_svc, "upload_file", return_value=None),
            pytest.raises(HTTPException) as exc,
        ):
            await storage_svc.upload(db, tenant.id, user.id, mock_upload)
        assert exc.value.status_code == 415

    async def test_get_file_not_found(self, db: AsyncSession, tenant):
        from app.modules.storage import service as storage_svc

        fake_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await storage_svc.get_file(db, tenant.id, fake_id)
        assert exc_info.value.status_code == 404

    async def test_get_file_success(self, db: AsyncSession, tenant, user):
        from app.modules.storage import service as storage_svc
        from app.modules.storage.models import File

        f = File(
            tenant_id=tenant.id,
            name="test.txt",
            original_name="test.txt",
            path="tenant/test.txt",
            size=100,
            mime_type="text/plain",
            uploaded_by=user.id,
        )
        db.add(f)
        await db.commit()
        await db.refresh(f)

        with patch.object(
            storage_svc, "get_presigned_url", return_value="https://signed"
        ) as mock_url:
            result = await storage_svc.get_file(db, tenant.id, f.id)

        assert result["id"] == f.id
        assert result["url"] == "https://signed"
        mock_url.assert_called_once_with(f.path)

    async def test_get_file_wrong_tenant(self, db: AsyncSession, tenant, user):
        from app.modules.storage import service as storage_svc
        from app.modules.storage.models import File

        f = File(
            tenant_id=tenant.id,
            name="secret.txt",
            original_name="secret.txt",
            path="tenant/secret.txt",
            size=50,
            mime_type="text/plain",
            uploaded_by=user.id,
        )
        db.add(f)
        await db.commit()
        await db.refresh(f)

        other_tenant_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await storage_svc.get_file(db, other_tenant_id, f.id)
        assert exc_info.value.status_code == 404

    async def test_delete_file(self, db: AsyncSession, tenant, user):
        from app.modules.storage import service as storage_svc
        from app.modules.storage.models import File

        f = File(
            tenant_id=tenant.id,
            name="del.txt",
            original_name="del.txt",
            path="tenant/del.txt",
            size=10,
            mime_type="text/plain",
            uploaded_by=user.id,
        )
        db.add(f)
        await db.commit()
        await db.refresh(f)

        with patch.object(storage_svc, "delete_file", return_value=True) as mock_del:
            await storage_svc.delete(db, tenant.id, f.id)

        mock_del.assert_called_once_with(f.path)

        # Verify record is deleted from DB
        deleted = await db.get(File, f.id)
        assert deleted is None

    async def test_delete_file_not_found(self, db: AsyncSession, tenant):
        from app.modules.storage import service as storage_svc

        with pytest.raises(HTTPException) as exc_info:
            await storage_svc.delete(db, tenant.id, uuid.uuid4())
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# ai/llm_client.py
# ---------------------------------------------------------------------------


class TestLLMClientResolveProvider:
    def test_resolve_claude(self):
        from app.modules.ai.llm_client import _resolve_provider

        assert _resolve_provider("claude-sonnet-4-20250514") == "claude"

    def test_resolve_gemini(self):
        from app.modules.ai.llm_client import _resolve_provider

        assert _resolve_provider("gemini-2.5-flash") == "gemini"

    def test_resolve_openai_explicit(self):
        from app.modules.ai.llm_client import _resolve_provider

        assert _resolve_provider("gpt-4o") == "openai"

    def test_resolve_from_settings(self):
        from app.modules.ai.llm_client import _resolve_provider

        with patch("app.modules.ai.llm_client.settings") as mock_settings:
            mock_settings.llm_provider = "gemini"
            assert _resolve_provider(None) == "gemini"


class TestLLMClientDefaultModel:
    def test_default_claude(self):
        from app.modules.ai.llm_client import _get_default_model

        with patch("app.modules.ai.llm_client.settings") as mock_settings:
            mock_settings.llm_provider = "claude"
            mock_settings.anthropic_api_key = "sk-ant-xxx"
            assert "claude" in _get_default_model()

    def test_default_gemini(self):
        from app.modules.ai.llm_client import _get_default_model

        with patch("app.modules.ai.llm_client.settings") as mock_settings:
            mock_settings.llm_provider = "gemini"
            mock_settings.anthropic_api_key = ""
            mock_settings.gemini_api_key = "gm-xxx"
            assert "gemini" in _get_default_model()

    def test_default_openai_fallback(self):
        from app.modules.ai.llm_client import _get_default_model

        with patch("app.modules.ai.llm_client.settings") as mock_settings:
            mock_settings.llm_provider = "openai"
            mock_settings.anthropic_api_key = ""
            mock_settings.gemini_api_key = ""
            assert "gpt" in _get_default_model()


class TestLLMClientGenerate:
    async def test_generate_openai(self):
        from app.modules.ai import llm_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello from GPT"))]

        mock_openai = AsyncMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm_client, "_resolve_provider", return_value="openai"),
            patch.object(llm_client, "_get_default_model", return_value="gpt-4o-mini"),
            patch.object(llm_client, "_get_openai", return_value=mock_openai),
        ):
            result = await llm_client.generate("Hello")

        assert result == "Hello from GPT"

    async def test_generate_anthropic(self):
        from app.modules.ai import llm_client

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(text="Hello from Claude")]

        mock_anthropic = AsyncMock()
        mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm_client, "_resolve_provider", return_value="claude"),
            patch.object(
                llm_client,
                "_get_default_model",
                return_value="claude-sonnet-4-20250514",
            ),
            patch.object(llm_client, "_get_anthropic", return_value=mock_anthropic),
        ):
            result = await llm_client.generate("Hello", system="Be helpful")

        assert result == "Hello from Claude"

    async def test_generate_gemini(self):
        from app.modules.ai import llm_client

        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini"

        mock_gemini = MagicMock()
        mock_gemini.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm_client, "_resolve_provider", return_value="gemini"),
            patch.object(
                llm_client, "_get_default_model", return_value="gemini-2.5-flash"
            ),
            patch.object(llm_client, "_get_gemini", return_value=mock_gemini),
        ):
            result = await llm_client.generate("Hello", system="System prompt")

        assert result == "Hello from Gemini"

    async def test_generate_exception_propagates(self, caplog):
        from app.modules.ai import llm_client

        with (
            patch.object(llm_client, "_resolve_provider", return_value="openai"),
            patch.object(llm_client, "_get_default_model", return_value="gpt-4o-mini"),
            patch.object(
                llm_client,
                "_generate_openai",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API down"),
            ),
            caplog.at_level(logging.CRITICAL, logger="app.modules.ai.llm_client"),
            pytest.raises(RuntimeError, match="API down"),
        ):
            await llm_client.generate("Hello")


class TestLLMClientGenerateJSON:
    async def test_generate_json_plain(self):
        from app.modules.ai import llm_client

        raw_json = json.dumps([{"title": "Test"}])
        with patch.object(
            llm_client, "generate", new_callable=AsyncMock, return_value=raw_json
        ):
            result = await llm_client.generate_json("prompt")

        assert result == [{"title": "Test"}]

    async def test_generate_json_with_markdown_block(self):
        from app.modules.ai import llm_client

        raw = '```json\n[{"title": "Wrapped"}]\n```'
        with patch.object(
            llm_client, "generate", new_callable=AsyncMock, return_value=raw
        ):
            result = await llm_client.generate_json("prompt")

        assert result == [{"title": "Wrapped"}]

    async def test_generate_json_with_generic_code_block(self):
        from app.modules.ai import llm_client

        raw = '```\n{"key": "value"}\n```'
        with patch.object(
            llm_client, "generate", new_callable=AsyncMock, return_value=raw
        ):
            result = await llm_client.generate_json("prompt")

        assert result == {"key": "value"}

    async def test_generate_json_invalid_json_raises(self):
        from app.modules.ai import llm_client

        with (
            patch.object(
                llm_client, "generate", new_callable=AsyncMock, return_value="not json"
            ),
            pytest.raises(json.JSONDecodeError),
        ):
            await llm_client.generate_json("prompt")


class TestClampAnthropicMaxTokens:
    """HRP-122: every Claude family has its own standard output cap.
    Asking for more without the extended-output beta header returns 400."""

    def test_haiku_cap_is_8k(self):
        from app.modules.ai.llm_client import _clamp_anthropic_max_tokens

        assert _clamp_anthropic_max_tokens("claude-haiku-4-5-20251001", 16384) == 8192
        # Smaller requests pass through unchanged.
        assert _clamp_anthropic_max_tokens("claude-haiku-4-5-20251001", 4000) == 4000

    def test_sonnet_allows_big_budgets(self):
        from app.modules.ai.llm_client import _clamp_anthropic_max_tokens

        assert _clamp_anthropic_max_tokens("claude-sonnet-5", 16384) == 16384

    def test_opus_clamped_at_32k(self):
        from app.modules.ai.llm_client import _clamp_anthropic_max_tokens

        assert _clamp_anthropic_max_tokens("claude-opus-4-8", 64000) == 32000

    def test_unknown_model_defaults_to_8k(self):
        from app.modules.ai.llm_client import _clamp_anthropic_max_tokens

        assert _clamp_anthropic_max_tokens("claude-future-model", 16384) == 8192


class TestLLMClientEmbedding:
    async def test_get_embedding(self):
        from app.modules.ai import llm_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

        mock_openai = AsyncMock()
        mock_openai.embeddings.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "_get_openai", return_value=mock_openai):
            result = await llm_client.get_embedding("test text")

        assert result == [0.1, 0.2, 0.3]
        mock_openai.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small", input=["test text"]
        )

    async def test_get_embeddings_batch(self):
        from app.modules.ai import llm_client

        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1, 0.2]),
            MagicMock(embedding=[0.3, 0.4]),
        ]

        mock_openai = AsyncMock()
        mock_openai.embeddings.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "_get_openai", return_value=mock_openai):
            result = await llm_client.get_embeddings_batch(["text1", "text2"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]


# ---------------------------------------------------------------------------
# ai/service.py
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_tenant_ai_settings():
    """Bypass `ai_settings_service.get_or_default` for tests that pass a
    MagicMock as db. The sync AI handlers load tenant settings via the real
    SQLAlchemy session, which a MagicMock can't honor.
    """
    from unittest.mock import MagicMock as _MM

    fake_settings = _MM()
    fake_settings.content_language = "en"
    fake_settings.company_context = None
    fake_settings.llm_model = None
    fake_settings.effort_level = "balanced"
    fake_settings.temperature = 0.3
    fake_settings.max_retries = 5

    with patch(
        "app.modules.ai.service.ai_settings_service.get_or_default",
        new_callable=AsyncMock,
        return_value=fake_settings,
    ):
        yield fake_settings


def _stub_ai_db():
    """Session double for the sync AI handlers.

    HRP-500 made the billing cost resolver consult the model catalog (the
    catalog, not the in-memory registry, is the source of truth), so the
    session these tests hand in must at least answer ``execute`` — an
    empty catalog is exactly the "nothing moderated here" case.
    """
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


class TestAIServiceGenerateCompetences:
    async def test_generate_competences_success(self, stub_tenant_ai_settings):
        from app.modules.ai import service as ai_svc

        expected = [{"title": "Group A", "competences": []}]

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            result = await ai_svc.generate_competences(
                _stub_ai_db(), uuid.uuid4(), uuid.uuid4(), "Software Engineer"
            )

        assert result == expected

    async def test_generate_competences_dict_wrapped_in_list(
        self, stub_tenant_ai_settings
    ):
        from app.modules.ai import service as ai_svc

        single = {"title": "Single"}

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            return_value=single,
        ):
            result = await ai_svc.generate_competences(
                _stub_ai_db(), uuid.uuid4(), uuid.uuid4(), "Designer"
            )

        assert result == [single]

    async def test_generate_competences_llm_error(self, stub_tenant_ai_settings):
        from app.modules.ai import service as ai_svc

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API error"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await ai_svc.generate_competences(
                    _stub_ai_db(), uuid.uuid4(), uuid.uuid4(), "Manager"
                )
            assert exc_info.value.status_code == 502


class TestAIServiceGenerateIndicators:
    async def test_generate_indicators_success(self, stub_tenant_ai_settings):
        from app.modules.ai import service as ai_svc

        indicators = [
            {"title": "Basic indicator", "skill_level": "basic", "weight": 1},
            {"title": "Advanced indicator", "skill_level": "advanced", "weight": 3},
        ]

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            return_value=indicators,
        ):
            result = await ai_svc.generate_indicators(
                _stub_ai_db(), uuid.uuid4(), uuid.uuid4(), "Leadership"
            )

        assert len(result) == 2

    async def test_generate_indicators_llm_error(self, stub_tenant_ai_settings):
        from app.modules.ai import service as ai_svc

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            side_effect=Exception("timeout"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await ai_svc.generate_indicators(
                    _stub_ai_db(), uuid.uuid4(), uuid.uuid4(), "Communication"
                )
            assert exc_info.value.status_code == 502


class TestAIServiceSuggestPDP:
    async def test_suggest_pdp_no_results(self, db: AsyncSession, tenant):
        from app.modules.ai import service as ai_svc

        fake_assessment_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await ai_svc.suggest_pdp(db, tenant.id, uuid.uuid4(), fake_assessment_id)
        assert exc_info.value.status_code == 404

    async def test_suggest_pdp_success(
        self,
        db: AsyncSession,
        tenant,
        user,
        employee,
        assessment_statuses,
        assessment_types,
    ):
        from app.modules.ai import service as ai_svc
        from app.modules.assessment.models import Assessment, AssessmentResult
        from app.modules.competence.models import Competence, CompetenceGroup

        # Create a competence group first
        group = CompetenceGroup(title="Test Group", tenant_id=tenant.id)
        db.add(group)
        await db.commit()
        await db.refresh(group)

        # Create competences
        comps = []
        for i in range(6):
            c = Competence(
                tenant_id=tenant.id,
                title=f"Comp {i}",
                group_id=group.id,
            )
            db.add(c)
            comps.append(c)
        await db.commit()
        for c in comps:
            await db.refresh(c)

        # Create assessment
        draft_status = assessment_statuses["draft"]
        a360 = assessment_types["360"]
        assessment = Assessment(
            tenant_id=tenant.id,
            employee_id=employee.id,
            type_id=a360.id,
            status_id=draft_status.id,
            initiator_id=user.id,
        )
        db.add(assessment)
        await db.commit()
        await db.refresh(assessment)

        # Create results with varying scores
        for i, comp in enumerate(comps):
            ar = AssessmentResult(
                assessment_id=assessment.id,
                competence_id=comp.id,
                avg_score=float(i + 1),
            )
            db.add(ar)
        await db.commit()

        pdp_items = [
            {
                "title": "Improve weak area",
                "description": "Focus on low-score competences",
            }
        ]

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            return_value=pdp_items,
        ):
            result = await ai_svc.suggest_pdp(
                db, tenant.id, uuid.uuid4(), assessment.id
            )

        assert result == pdp_items


class TestAIServiceGeneratePositions:
    async def test_regenerate_reuses_existing_draft_with_same_title(
        self, db: AsyncSession, tenant
    ):
        """LLM may return a title that already exists as ai_draft from a
        previous run — must update in place, not insert a duplicate that
        violates uq_position_tenant_title (Sentry issue 7447918527)."""
        from app.modules.ai import service as ai_svc
        from app.modules.position.models import Position

        old = Position(
            tenant_id=tenant.id,
            title="Principal Data Scientist",
            description="old description",
            source="ai_draft",
        )
        db.add(old)
        await db.commit()
        old_id = old.id

        llm_payload = [
            {
                "title": "Principal Data Scientist",
                "description": "fresh description",
            },
            {"title": "Brand New Role", "description": "new"},
        ]

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            return_value=llm_payload,
        ):
            await ai_svc.generate_positions(db, tenant.id, uuid.uuid4())

        from sqlalchemy import select as _select

        rows = (
            (
                await db.execute(
                    _select(Position).where(
                        Position.tenant_id == tenant.id,
                        Position.title == "Principal Data Scientist",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == old_id
        assert rows[0].description == "fresh description"

    async def test_regenerate_skips_manual_titles(self, db: AsyncSession, tenant):
        from app.modules.ai import service as ai_svc
        from app.modules.position.models import Position

        manual = Position(
            tenant_id=tenant.id,
            title="Tech Lead",
            description="manual entry",
            source="manual",
        )
        db.add(manual)
        await db.commit()

        with patch(
            "app.modules.ai.llm_client.generate_json",
            new_callable=AsyncMock,
            return_value=[
                {"title": "Tech Lead", "description": "should be ignored"},
                {"title": "Junior Dev", "description": "ok"},
            ],
        ):
            await ai_svc.generate_positions(db, tenant.id, uuid.uuid4())

        from sqlalchemy import select as _select

        all_rows = (
            (await db.execute(_select(Position).where(Position.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        by_title = {p.title: p for p in all_rows}
        assert by_title["Tech Lead"].source == "manual"
        assert by_title["Tech Lead"].description == "manual entry"
        assert by_title["Junior Dev"].source == "ai_draft"


class TestAIServiceCreateEmbedding:
    async def test_create_embedding_new(self, db: AsyncSession):
        from app.modules.ai import service as ai_svc

        entity_id = uuid.uuid4()
        fake_vector = [0.1] * 1536

        with patch(
            "app.modules.ai.llm_client.get_embedding",
            new_callable=AsyncMock,
            return_value=fake_vector,
        ):
            result = await ai_svc.create_embedding(
                db, "competence", entity_id, "Leadership skills"
            )

        assert result["entity_type"] == "competence"
        assert result["entity_id"] == str(entity_id)
        assert result["status"] == "stored"

    async def test_create_embedding_upsert(self, db: AsyncSession):
        from app.modules.ai import service as ai_svc
        from app.modules.ai.models import Embedding

        entity_id = uuid.uuid4()
        fake_vector = [0.1] * 1536

        # Create initial embedding
        emb = Embedding(
            entity_type="competence",
            entity_id=entity_id,
            text_content="Old text",
            embedding=fake_vector,
        )
        db.add(emb)
        await db.commit()

        new_vector = [0.2] * 1536
        with patch(
            "app.modules.ai.llm_client.get_embedding",
            new_callable=AsyncMock,
            return_value=new_vector,
        ):
            result = await ai_svc.create_embedding(
                db, "competence", entity_id, "Updated text"
            )

        assert result["status"] == "stored"

        # Verify it was updated, not duplicated
        from sqlalchemy import select

        rows = await db.execute(
            select(Embedding).where(
                Embedding.entity_type == "competence",
                Embedding.entity_id == entity_id,
            )
        )
        all_embs = rows.scalars().all()
        assert len(all_embs) == 1
        assert all_embs[0].text_content == "Updated text"
