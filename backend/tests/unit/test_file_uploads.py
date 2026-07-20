"""Tests for Phase H: File Uploads — avatar, PDP attachments, exam images."""

from io import BytesIO
from unittest.mock import patch

import pytest
from app.modules.assessment import pdp_service
from app.modules.assessment.schemas import PDPCommentCreate, PDPMaterialCreate
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import UserUpdate
from app.modules.exam import service as exam_service
from app.modules.exam.schemas import OptionCreate, QuestionCreate
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

# --- Helpers ---


# Real magic-byte prefixes so uploads survive the storage-layer content sniff
# (app.core.upload_validation). Image types are byte-checked; docs are not.
_MAGIC = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff\xe0",
    "image/gif": b"GIF89a",
    "image/webp": b"RIFF\x00\x00\x00\x00WEBP",
}


def _make_upload(
    filename: str = "test.png",
    content: bytes | None = None,
    content_type: str = "image/png",
) -> UploadFile:
    if content is None:
        # Prepend a valid signature for image types so the sniff passes.
        content = _MAGIC.get(content_type, b"") + b"payload-bytes"
    return UploadFile(
        filename=filename, file=BytesIO(content), headers={"content-type": content_type}
    )


@pytest.fixture
def mock_s3():
    """Mock S3 operations to avoid real S3 calls in tests."""
    url = "https://s3.example.com/presigned/test.png"
    with (
        patch(
            "app.modules.storage.service.upload_file",
            return_value="https://s3.example.com/test.png",
        ),
        patch("app.modules.storage.service.delete_file", return_value=True),
        patch("app.modules.storage.service.get_presigned_url", return_value=url),
        patch("app.modules.auth.service.get_presigned_url", return_value=url),
        patch("app.modules.assessment.pdp_service.get_presigned_url", return_value=url),
        patch("app.modules.exam.service.get_presigned_url", return_value=url),
    ):
        yield


# ===========================================================================
# H1: Avatar upload
# ===========================================================================


class TestAvatarUpload:
    async def test_upload_avatar(self, db: AsyncSession, user, tenant, mock_s3):
        result = await auth_service.upload_avatar(
            db, user.id, tenant.id, _make_upload()
        )
        assert result["avatar_url"] is not None
        assert result["id"] == user.id

    async def test_upload_avatar_replaces_old(
        self, db: AsyncSession, user, tenant, mock_s3
    ):
        # First upload
        await auth_service.upload_avatar(
            db, user.id, tenant.id, _make_upload("first.png")
        )
        # Second upload replaces first
        result = await auth_service.upload_avatar(
            db, user.id, tenant.id, _make_upload("second.png")
        )
        assert result["avatar_url"] is not None

    async def test_remove_avatar(self, db: AsyncSession, user, tenant, mock_s3):
        await auth_service.upload_avatar(db, user.id, tenant.id, _make_upload())
        result = await auth_service.remove_avatar(db, user.id, tenant.id)
        assert result["avatar_url"] is None

    async def test_remove_avatar_no_avatar(
        self, db: AsyncSession, user, tenant, mock_s3
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_service.remove_avatar(db, user.id, tenant.id)
        assert exc.value.status_code == 400

    async def test_get_me_includes_avatar_url(
        self, db: AsyncSession, user, tenant, mock_s3
    ):
        await auth_service.upload_avatar(db, user.id, tenant.id, _make_upload())
        me = await auth_service.get_me(db, user.id)
        assert me["avatar_url"] is not None

    async def test_get_me_no_avatar(self, db: AsyncSession, user, tenant, mock_s3):
        me = await auth_service.get_me(db, user.id)
        assert me["avatar_url"] is None

    async def test_update_profile_preserves_avatar(
        self, db: AsyncSession, user, tenant, mock_s3
    ):
        await auth_service.upload_avatar(db, user.id, tenant.id, _make_upload())
        result = await auth_service.update_profile(
            db, user.id, UserUpdate(first_name="Updated")
        )
        assert result["avatar_url"] is not None
        assert result["first_name"] == "Updated"


# ===========================================================================
# H2: PDP attachments
# ===========================================================================


@pytest.fixture
async def pdp_with_item(
    db: AsyncSession, tenant, user, employee, assessment_statuses, assessment_types
):
    """Create a PDP with one item for attachment tests."""
    from app.modules.assessment.schemas import PDPCreate, PDPItemCreate

    pdp = await pdp_service.create_pdp(
        db,
        tenant.id,
        user.id,
        PDPCreate(title="Plan", employee_id=employee.id),
    )
    item = await pdp_service.add_item(
        db,
        tenant.id,
        pdp["id"],
        PDPItemCreate(title="Learn Python"),
    )
    return pdp, item


class TestPDPCommentAttachment:
    async def test_add_comment_with_file(
        self, db: AsyncSession, tenant, user, pdp_with_item, mock_s3
    ):
        pdp, item = pdp_with_item
        # Upload a file first
        from app.modules.storage import service as storage_svc

        file_data = await storage_svc.upload(
            db,
            tenant.id,
            user.id,
            _make_upload("report.pdf", b"pdf-data", "application/pdf"),
            entity_type="pdp_comment",
        )

        comment = await pdp_service.add_comment(
            db,
            tenant.id,
            pdp["id"],
            user.id,
            PDPCommentCreate(text="See attached report", file_id=file_data["id"]),
        )
        assert comment["file_id"] == file_data["id"]
        assert comment["file_url"] is not None
        assert comment["file_name"] == "report.pdf"

    async def test_add_comment_without_file(
        self, db: AsyncSession, tenant, user, pdp_with_item, mock_s3
    ):
        pdp, item = pdp_with_item
        comment = await pdp_service.add_comment(
            db,
            tenant.id,
            pdp["id"],
            user.id,
            PDPCommentCreate(text="Just a text comment"),
        )
        assert comment["file_id"] is None
        assert comment["file_url"] is None
        assert comment["file_name"] is None

    async def test_pdp_detail_includes_comment_file(
        self, db: AsyncSession, tenant, user, pdp_with_item, mock_s3
    ):
        pdp, item = pdp_with_item
        from app.modules.storage import service as storage_svc

        file_data = await storage_svc.upload(
            db,
            tenant.id,
            user.id,
            _make_upload("doc.pdf"),
        )
        await pdp_service.add_comment(
            db,
            tenant.id,
            pdp["id"],
            user.id,
            PDPCommentCreate(text="With attachment", file_id=file_data["id"]),
        )
        detail = await pdp_service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["comments"]) == 1
        assert detail["comments"][0]["file_id"] == file_data["id"]


class TestPDPMaterialAttachment:
    async def test_add_material_with_file(
        self, db: AsyncSession, tenant, user, pdp_with_item, mock_s3
    ):
        pdp, item = pdp_with_item
        from app.modules.storage import service as storage_svc

        file_data = await storage_svc.upload(
            db,
            tenant.id,
            user.id,
            _make_upload("slides.pptx", b"pptx-data", "application/vnd.ms-powerpoint"),
        )

        mat = await pdp_service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Training slides", file_id=file_data["id"]),
        )
        assert mat["file_id"] == file_data["id"]
        assert mat["file_url"] is not None
        assert mat["file_name"] == "slides.pptx"

    async def test_add_material_without_file(
        self, db: AsyncSession, tenant, user, pdp_with_item, mock_s3
    ):
        pdp, item = pdp_with_item
        mat = await pdp_service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Online course", link="https://example.com"),
        )
        assert mat["file_id"] is None
        assert mat["file_url"] is None

    async def test_pdp_detail_includes_material_file(
        self, db: AsyncSession, tenant, user, pdp_with_item, mock_s3
    ):
        pdp, item = pdp_with_item
        from app.modules.storage import service as storage_svc

        file_data = await storage_svc.upload(
            db,
            tenant.id,
            user.id,
            _make_upload("book.pdf"),
        )
        await pdp_service.add_material(
            db,
            tenant.id,
            pdp["id"],
            item["id"],
            PDPMaterialCreate(title="Book PDF", file_id=file_data["id"]),
        )
        detail = await pdp_service.get_pdp_detail(db, tenant.id, pdp["id"])
        assert len(detail["items"]) == 1
        assert len(detail["items"][0]["materials"]) == 1
        assert detail["items"][0]["materials"][0]["file_id"] == file_data["id"]


# ===========================================================================
# H3: Exam question images
# ===========================================================================


@pytest.fixture
async def mass_exam(db: AsyncSession, tenant, user):
    from app.modules.exam.schemas import MassExamCreate

    return await exam_service.create_mass_exam(
        db,
        tenant.id,
        user.id,
        MassExamCreate(title="Python Basics"),
    )


class TestExamQuestionImage:
    async def test_add_question_with_image(
        self, db: AsyncSession, tenant, user, mass_exam, mock_s3
    ):
        from app.modules.storage import service as storage_svc

        file_data = await storage_svc.upload(
            db,
            tenant.id,
            user.id,
            _make_upload("diagram.png"),
            entity_type="exam_question",
        )

        q = await exam_service.add_question(
            db,
            tenant.id,
            mass_exam["id"],
            QuestionCreate(
                title="What does this diagram show?",
                question_type="single_choice",
                image_file_id=file_data["id"],
                options=[
                    OptionCreate(title="A class diagram", is_correct=True),
                    OptionCreate(title="A sequence diagram"),
                ],
            ),
        )
        assert q["image_file_id"] == file_data["id"]
        assert q["image_url"] is not None

    async def test_add_question_without_image(
        self, db: AsyncSession, tenant, user, mass_exam, mock_s3
    ):
        q = await exam_service.add_question(
            db,
            tenant.id,
            mass_exam["id"],
            QuestionCreate(
                title="What is Python?",
                question_type="single_choice",
                options=[
                    OptionCreate(title="A snake", is_correct=False),
                    OptionCreate(title="A programming language", is_correct=True),
                ],
            ),
        )
        assert q["image_file_id"] is None
        assert q["image_url"] is None

    async def test_mass_exam_detail_includes_image(
        self, db: AsyncSession, tenant, user, mass_exam, mock_s3
    ):
        from app.modules.storage import service as storage_svc

        file_data = await storage_svc.upload(
            db,
            tenant.id,
            user.id,
            _make_upload("chart.png"),
        )
        await exam_service.add_question(
            db,
            tenant.id,
            mass_exam["id"],
            QuestionCreate(
                title="Identify the chart",
                question_type="essay",
                image_file_id=file_data["id"],
            ),
        )
        detail = await exam_service.get_mass_exam_detail(db, tenant.id, mass_exam["id"])
        assert len(detail["questions"]) == 1
        assert detail["questions"][0]["image_file_id"] == file_data["id"]
        assert detail["questions"][0]["image_url"] is not None

    async def test_question_without_image_in_detail(
        self, db: AsyncSession, tenant, user, mass_exam, mock_s3
    ):
        await exam_service.add_question(
            db,
            tenant.id,
            mass_exam["id"],
            QuestionCreate(
                title="Text only question",
                question_type="essay",
            ),
        )
        detail = await exam_service.get_mass_exam_detail(db, tenant.id, mass_exam["id"])
        assert detail["questions"][0]["image_file_id"] is None
        assert detail["questions"][0]["image_url"] is None
