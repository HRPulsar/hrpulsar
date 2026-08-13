"""HRP-244: email notifications on PDP status transitions.

Covers six new transitions:
- Sent → Review            (notify reviewer)
- Review → Returned        (notify owner)
- Review → Done            (notify owner + reviewer)
- {Sent, In progress, Review, Returned} → Cancelled (notify owner + reviewer)

The Draft → Sent path is already exercised in TestPDPDraftSentEmail; we add
its negative twin here (Draft → Cancelled stays silent) to spell out the
post-launch gate for cancellations.
"""

import uuid
from datetime import date

import pytest
from app.core.email_templates import (
    render_pdp_cancelled_to_employee_email,
    render_pdp_cancelled_to_reviewer_email,
    render_pdp_done_to_employee_email,
    render_pdp_done_to_reviewer_email,
    render_pdp_returned_email,
    render_pdp_review_submitted_email,
)
from app.modules.assessment import pdp_service
from app.modules.assessment.schemas import (
    PDPCreate,
    PDPItemCreate,
    PDPMaterialCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Template-level rendering
# ---------------------------------------------------------------------------


class TestHRP244Templates:
    def test_review_submitted_subject_includes_title(self):
        subject, html = render_pdp_review_submitted_email(
            "Ivan Owner", pdp_title="Q3 Growth Plan"
        )
        assert (
            subject
            == "Your employee's development plan submitted for review: Q3 Growth Plan"
        )
        assert "Ivan Owner" in html
        assert "Q3 Growth Plan" in html

    def test_review_submitted_no_title_falls_back(self):
        subject, _ = render_pdp_review_submitted_email("Ivan Owner")
        assert subject == "Your employee's development plan submitted for review"

    def test_review_submitted_escapes_title(self):
        _, html = render_pdp_review_submitted_email(
            "Ivan Owner", pdp_title="<script>alert(1)</script>"
        )
        assert "<script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_returned_subject_includes_title(self):
        subject, html = render_pdp_returned_email(
            "Jane Smith", pdp_title="Q3 Growth Plan"
        )
        assert subject == "Development plan returned: Q3 Growth Plan"
        assert "Jane Smith" in html
        assert "Q3 Growth Plan" in html

    def test_returned_blank_title_falls_back(self):
        subject, _ = render_pdp_returned_email("Jane Smith", pdp_title="   ")
        assert subject == "Development plan returned"

    def test_done_to_employee(self):
        subject, html = render_pdp_done_to_employee_email(
            "Ivan Owner", pdp_title="Q3 Growth Plan"
        )
        assert subject == "Your development plan completed: Q3 Growth Plan"
        assert "Ivan Owner" in html

    def test_done_to_reviewer(self):
        subject, html = render_pdp_done_to_reviewer_email(
            "Ivan Owner", pdp_title="Q3 Growth Plan"
        )
        assert subject == "Your employee's development plan completed: Q3 Growth Plan"
        assert "Ivan Owner" in html

    def test_cancelled_to_employee(self):
        subject, html = render_pdp_cancelled_to_employee_email(
            "Ivan Owner", pdp_title="Q3 Growth Plan"
        )
        assert subject == "Your development plan cancelled: Q3 Growth Plan"
        assert "Ivan Owner" in html

    def test_cancelled_to_reviewer(self):
        subject, html = render_pdp_cancelled_to_reviewer_email(
            "Ivan Owner", pdp_title="Q3 Growth Plan"
        )
        assert subject == "Your employee's development plan cancelled: Q3 Growth Plan"
        assert "Ivan Owner" in html

    def test_noname_variants_drop_the_placeholder(self):
        # HRP-584: employee_name=None must render dedicated nameless copy
        # instead of a "The employee" stand-in (in ru the label and the
        # generic fallback name used to collide into the same word twice).
        for render in (
            render_pdp_done_to_employee_email,
            render_pdp_done_to_reviewer_email,
            render_pdp_cancelled_to_employee_email,
            render_pdp_cancelled_to_reviewer_email,
        ):
            for title in ("Q3 Growth Plan", None):
                subject, html = render(None, pdp_title=title)
                assert "The employee" not in html, (render.__name__, title)
                assert "{employee_name}" not in html, (render.__name__, title)
                if title:
                    assert title in subject

    def test_employee_name_is_html_escaped(self):
        # HRP-584 review: the name is user-editable profile data and lands
        # inside markup — it must be escaped like the title next to it.
        _, html = render_pdp_done_to_reviewer_email(
            '</strong><a href="http://evil">x</a>', pdp_title="Q3 Growth Plan"
        )
        assert '<a href="http://evil">' not in html
        assert "&lt;a href=&#34;http://evil&#34;&gt;" in html


# ---------------------------------------------------------------------------
# Service-level wiring
# ---------------------------------------------------------------------------


async def _seed_item(db, tenant_id, pdp_id):
    item = await pdp_service.add_item(
        db, tenant_id, pdp_id, PDPItemCreate(title="Seed")
    )
    await pdp_service.add_material(
        db,
        tenant_id,
        pdp_id,
        item["id"],
        PDPMaterialCreate(title="Mat", link="https://example.com"),
    )
    return item


async def _make_reviewer(db, tenant, *, email_suffix: str | None = None):
    from app.core.security import hash_password
    from app.modules.auth.models import User

    reviewer = User(
        email=f"rev-{email_suffix or uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("x"),
        first_name="Anna",
        last_name="Reviewer",
        tenant_id=tenant.id,
    )
    db.add(reviewer)
    await db.commit()
    await db.refresh(reviewer)
    return reviewer


async def _pdp_with_reviewer(db, tenant, user, employee):
    reviewer = await _make_reviewer(db, tenant)
    pdp = await pdp_service.create_pdp(
        db,
        tenant.id,
        user.id,
        PDPCreate(
            title="Q3 Growth Plan", employee_id=employee.id, reviewer_id=reviewer.id
        ),
    )
    await _seed_item(db, tenant.id, pdp["id"])
    return pdp, reviewer


async def _drive_to_review(db, tenant, pdp_id):
    """Walk the plan from draft → sent → in_progress → review."""
    await pdp_service.change_pdp_status(db, tenant.id, pdp_id, "sent")
    await pdp_service.change_pdp_status(
        db, tenant.id, pdp_id, "in_progress", bypass_transition_check=True
    )
    await pdp_service.change_pdp_status(db, tenant.id, pdp_id, "review")


@pytest.fixture
def capture_emails(monkeypatch):
    calls: list[dict] = []

    def fake_enqueue(to, subject, body, **kwargs):
        calls.append({"to": to, "subject": subject, "body": body, "kwargs": kwargs})

    monkeypatch.setattr("app.core.email.enqueue_email", fake_enqueue)
    return calls


class TestHRP244ServiceHooks:
    async def test_sent_to_review_notifies_reviewer(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        pdp, reviewer = await _pdp_with_reviewer(db, tenant, user, employee)
        await _drive_to_review(db, tenant, pdp["id"])

        review_calls = [
            c
            for c in capture_emails
            if c["kwargs"].get("template_code") == "pdp.review_submitted"
        ]
        assert len(review_calls) == 1
        assert review_calls[0]["to"] == reviewer.email
        assert (
            review_calls[0]["subject"]
            == "Your employee's development plan submitted for review: Q3 Growth Plan"
        )

    async def test_review_to_returned_notifies_owner(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        pdp, _ = await _pdp_with_reviewer(db, tenant, user, employee)
        await _drive_to_review(db, tenant, pdp["id"])
        capture_emails.clear()

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "returned")

        returned_calls = [
            c
            for c in capture_emails
            if c["kwargs"].get("template_code") == "pdp.returned"
        ]
        assert len(returned_calls) == 1
        assert returned_calls[0]["to"] == user.email
        assert (
            returned_calls[0]["subject"] == "Development plan returned: Q3 Growth Plan"
        )

    async def test_review_to_done_notifies_owner_and_reviewer(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        pdp, reviewer = await _pdp_with_reviewer(db, tenant, user, employee)
        await _drive_to_review(db, tenant, pdp["id"])
        capture_emails.clear()

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "done")

        templates = {
            c["kwargs"].get("template_code"): c
            for c in capture_emails
            if c["kwargs"].get("template_code", "").startswith("pdp.done")
        }
        assert set(templates) == {"pdp.done.employee", "pdp.done.reviewer"}
        assert templates["pdp.done.employee"]["to"] == user.email
        assert templates["pdp.done.reviewer"]["to"] == reviewer.email

    async def test_done_emails_render_in_each_recipient_locale(
        self, db: AsyncSession, tenant, user, employee, capture_emails, monkeypatch
    ):
        # i18n F4 (HRP-478): a two-address event resolves the locale per
        # recipient. The owner states English explicitly; the reviewer has
        # no preference and inherits the German tenant default.
        from app.config import settings

        monkeypatch.setattr(settings, "available_locales", "de,en")
        monkeypatch.setattr(settings, "default_locale", "en")

        pdp, reviewer = await _pdp_with_reviewer(db, tenant, user, employee)
        tenant.default_locale = "de"
        user.language = "en"
        await db.commit()

        await _drive_to_review(db, tenant, pdp["id"])
        capture_emails.clear()

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "done")

        by_recipient = {
            c["to"]: c["body"]
            for c in capture_emails
            if c["kwargs"].get("template_code", "").startswith("pdp.done")
        }
        assert (
            '<html lang="en">' in by_recipient[user.email]
        ), "User.language must beat the tenant default for the plan owner's own email"
        assert (
            '<html lang="de">' in by_recipient[reviewer.email]
        ), "A reviewer without a language preference falls back to the tenant default"

    async def test_post_launch_cancel_notifies_owner_and_reviewer(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        pdp, reviewer = await _pdp_with_reviewer(db, tenant, user, employee)
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "sent")
        capture_emails.clear()

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")

        templates = {
            c["kwargs"].get("template_code"): c
            for c in capture_emails
            if c["kwargs"].get("template_code", "").startswith("pdp.cancelled")
        }
        assert set(templates) == {
            "pdp.cancelled.employee",
            "pdp.cancelled.reviewer",
        }
        assert templates["pdp.cancelled.employee"]["to"] == user.email
        assert templates["pdp.cancelled.reviewer"]["to"] == reviewer.email

    async def test_draft_to_cancelled_stays_silent(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        # HRP-244 spec lists Sent/In progress/Review/Returned as the
        # cancellation sources that should notify — Draft is intentionally
        # silent because the employee never saw the plan.
        pdp = await pdp_service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(title="Draft Plan", employee_id=employee.id),
        )
        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "cancelled")
        assert capture_emails == []

    async def test_review_with_only_division_manager_falls_back(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        # HRP-130: when no explicit reviewer is set, the division manager
        # plays the reviewer role. The notification has to follow the
        # same fallback so manager-as-implicit-reviewer still gets emailed.
        from app.core.security import hash_password
        from app.modules.auth.models import User
        from app.modules.company.models import Division
        from app.modules.employee.models import Employee

        manager_user = User(
            email=f"mgr-{uuid.uuid4().hex[:8]}@test.com",
            password_hash=hash_password("x"),
            first_name="Mike",
            last_name="Manager",
            tenant_id=tenant.id,
        )
        db.add(manager_user)
        await db.flush()
        manager_emp = Employee(
            user_id=manager_user.id,
            tenant_id=tenant.id,
            hire_date=date(2024, 1, 1),
        )
        db.add(manager_emp)
        await db.flush()
        division = Division(
            name="Engineering",
            tenant_id=tenant.id,
            manager_id=manager_emp.id,
        )
        db.add(division)
        await db.flush()
        employee.division_id = division.id
        await db.commit()

        pdp = await pdp_service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(title="Q3 Growth Plan", employee_id=employee.id),
        )
        await _seed_item(db, tenant.id, pdp["id"])
        await _drive_to_review(db, tenant, pdp["id"])

        review_calls = [
            c
            for c in capture_emails
            if c["kwargs"].get("template_code") == "pdp.review_submitted"
        ]
        assert len(review_calls) == 1
        assert review_calls[0]["to"] == manager_user.email

    async def test_self_managed_owner_does_not_email_self_on_submit(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        # HRP-244 post-review fix: when the plan owner manages their own
        # division, the reviewer-fallback resolves back to the owner. The
        # done / cancelled hooks already guarded this; review-submitted now
        # mirrors them — the owner must not receive a "your employee
        # submitted their plan" email about themselves.
        from app.modules.company.models import Division

        division = Division(
            name="Solo Division",
            tenant_id=tenant.id,
            manager_id=employee.id,
        )
        db.add(division)
        await db.flush()
        employee.division_id = division.id
        await db.commit()

        pdp = await pdp_service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(title="Solo Plan", employee_id=employee.id),
        )
        await _seed_item(db, tenant.id, pdp["id"])
        await _drive_to_review(db, tenant, pdp["id"])

        review_calls = [
            c
            for c in capture_emails
            if c["kwargs"].get("template_code") == "pdp.review_submitted"
        ]
        assert review_calls == []

    async def test_done_reaches_reviewer_when_owner_has_no_user(
        self, db: AsyncSession, tenant, user, employee, capture_emails, monkeypatch
    ):
        # HRP-244 post-review fix: the reviewer must still hear about a
        # done / cancelled transition even when the owner record is gone.
        # The earlier implementation bailed at `if not owner: return` after
        # resolving the reviewer, silently losing the notification.
        reviewer = await _make_reviewer(db, tenant)
        pdp = await pdp_service.create_pdp(
            db,
            tenant.id,
            user.id,
            PDPCreate(
                title="Orphan Plan",
                employee_id=employee.id,
                reviewer_id=reviewer.id,
            ),
        )
        await _seed_item(db, tenant.id, pdp["id"])
        await _drive_to_review(db, tenant, pdp["id"])
        capture_emails.clear()

        # Simulate the "owner record gone" path without violating the
        # employees.user_id NOT NULL constraint — only the notification
        # helpers consult _pdp_owner_user, so monkeypatching it captures
        # the post-soft-delete behaviour faithfully.
        monkeypatch.setattr(pdp_service, "_pdp_owner_user", lambda _p: None)

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "done")

        reviewer_calls = [
            c
            for c in capture_emails
            if c["kwargs"].get("template_code") == "pdp.done.reviewer"
        ]
        assert len(reviewer_calls) == 1
        assert reviewer_calls[0]["to"] == reviewer.email
        # HRP-584: the missing owner renders the nameless copy, not a
        # generic "The employee" placeholder name.
        from app.core.i18n import translate

        assert "The employee" not in reviewer_calls[0]["body"]
        assert (
            translate(
                "email.pdp_done_to_reviewer.intro_noname", "en", title="Orphan Plan"
            )
            in reviewer_calls[0]["body"]
        )
        employee_calls = [
            c
            for c in capture_emails
            if c["kwargs"].get("template_code") == "pdp.done.employee"
        ]
        assert employee_calls == []

    async def test_blank_name_owner_gets_nameless_copy(
        self, db: AsyncSession, tenant, user, employee, capture_emails
    ):
        # HRP-584: an owner whose profile carries empty first/last names
        # (CSV/SCIM onboarding) must get the nameless wording — their login
        # email must not be rendered as a display name.
        pdp, reviewer = await _pdp_with_reviewer(db, tenant, user, employee)
        user.first_name = ""
        user.last_name = ""
        await db.commit()
        await _drive_to_review(db, tenant, pdp["id"])
        capture_emails.clear()

        await pdp_service.change_pdp_status(db, tenant.id, pdp["id"], "done")

        by_template = {
            c["kwargs"].get("template_code"): c
            for c in capture_emails
            if c["kwargs"].get("template_code", "").startswith("pdp.done")
        }
        assert set(by_template) == {"pdp.done.employee", "pdp.done.reviewer"}
        for call in by_template.values():
            assert user.email not in call["body"]
            assert "The employee" not in call["body"]
