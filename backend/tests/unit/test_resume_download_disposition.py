"""HRP-347: resume download must serve the file, not a JSON envelope.

The candidate-page Files block now requests ``disposition=attachment`` so
the presigned URL forces a browser download with the original filename;
the default ``inline`` keeps the resume preview iframe working.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core import s3
from app.modules.recruitment.candidate_service import _attachment_disposition


class TestAttachmentDisposition:
    def test_ascii_filename(self) -> None:
        value = _attachment_disposition("resume.pdf")
        assert value.startswith('attachment; filename="resume.pdf"')
        assert "filename*=UTF-8''resume.pdf" in value

    def test_cyrillic_filename_keeps_ascii_fallback(self) -> None:
        value = _attachment_disposition("Иванова Мария (1).pdf")
        # ASCII fallback must not contain raw non-ASCII bytes.
        assert 'filename=" (1).pdf"' in value or 'filename="(1).pdf"' in value
        assert "filename*=UTF-8''%D0%98" in value

    def test_empty_and_hostile_filenames(self) -> None:
        assert 'filename="resume"' in _attachment_disposition("Резюме")
        assert '\\"' not in _attachment_disposition('a"b\\c.pdf')
        # Control chars must never reach the header value (injection shape).
        assert "\r" not in _attachment_disposition("line\r\nbreak.pdf")
        assert "\n" not in _attachment_disposition("line\r\nbreak.pdf")
        # Fully non-ASCII stem keeps the extension on the fallback.
        assert 'filename="resume.pdf"' in _attachment_disposition("резюме.pdf")


class TestPresignedUrlDisposition:
    def test_content_disposition_forwarded_to_boto(self) -> None:
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://s3/signed"
        with patch.object(s3, "get_s3_client", return_value=client):
            url = s3.get_presigned_url(
                "tenant/resumes/x.pdf",
                content_disposition='attachment; filename="x.pdf"',
            )
        assert url == "https://s3/signed"
        params = client.generate_presigned_url.call_args.kwargs["Params"]
        assert params["ResponseContentDisposition"] == 'attachment; filename="x.pdf"'

    def test_no_disposition_keeps_params_clean(self) -> None:
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://s3/signed"
        with patch.object(s3, "get_s3_client", return_value=client):
            s3.get_presigned_url("tenant/resumes/x.pdf")
        params = client.generate_presigned_url.call_args.kwargs["Params"]
        assert "ResponseContentDisposition" not in params
