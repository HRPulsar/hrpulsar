"""HRP-276 / C1 — demo candidate creation must not leak Person PII.

The dedup branch in :func:`recruitment.service.create_candidate` runs a
global ``SELECT Person WHERE lower(email) = X`` (no tenant filter). For
demo tenants that lookup is disabled — otherwise a demo session could
probe known company emails and have first/last name + phone of a real
user attached to the response payload.

This module pins:

* For a **demo tenant**, ``create_candidate`` with an email that already
  exists in another (paid) tenant's Person registry creates a **fresh
  Person** scoped to the candidate, with the demo-supplied names — none
  of the paid tenant's PII is reflected back. A second call with the
  same email also succeeds (no spurious 409).
* For a **paid tenant**, the dedup logic continues to fire: a second
  candidate creation with the same email re-uses the existing Person
  (regression guard against accidentally widening the demo skip).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from app.core.security import hash_password
from app.models import Person
from app.modules.auth.models import User
from app.modules.company.models import Tenant
from app.modules.recruitment import service as recruitment_service
from app.modules.recruitment.schemas import CandidateCreate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_tenant(db: AsyncSession, *, is_demo: bool) -> tuple[Tenant, User]:
    """Make a tenant + one admin user (audit FK target)."""
    suffix = uuid.uuid4().hex[:6]
    label = "demo" if is_demo else "paid"
    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"{label}-{suffix}",
        slug=f"{label}-{suffix}",
        is_demo=is_demo,
    )
    db.add(tenant)
    await db.flush()
    user = User(
        id=uuid.uuid4(),
        email=f"{label}-admin-{suffix}@example.com",
        password_hash=hash_password("pw12345678"),
        first_name=label.title(),
        last_name="Owner",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(user)
    return tenant, user


@pytest_asyncio.fixture
async def paid_tenant_with_person(
    db: AsyncSession,
) -> tuple[Tenant, User, Person]:
    """Paid tenant that already owns a Person row for ceo@example.com."""
    tenant, user = await _make_tenant(db, is_demo=False)
    person = Person(
        first_name="Real",
        last_name="Owner",
        middle_name="Confidential",
        email=f"ceo-{uuid.uuid4().hex[:6]}@example.com",
        phone="+1-555-PRIVATE",
    )
    db.add(person)
    await db.commit()
    await db.refresh(person)
    return tenant, user, person


@pytest_asyncio.fixture
async def demo_tenant_with_user(db: AsyncSession) -> tuple[Tenant, User]:
    return await _make_tenant(db, is_demo=True)


@pytest.mark.asyncio
async def test_demo_create_candidate_skips_dedup_and_does_not_leak_pii(
    db: AsyncSession,
    paid_tenant_with_person: tuple[Tenant, User, Person],
    demo_tenant_with_user: tuple[Tenant, User],
) -> None:
    _paid, _paid_user, paid_person = paid_tenant_with_person
    demo, demo_user = demo_tenant_with_user

    payload = CandidateCreate(
        first_name="Anon",
        last_name="Tester",
        middle_name=None,
        email=paid_person.email,
        phone="+1-000-NEW",
        source="demo",
        notes=None,
    )
    result = await recruitment_service.create_candidate(
        db, demo.id, user_id=demo_user.id, data=payload
    )

    # A fresh Person was created — not the paid tenant's row.
    assert result["person_id"] != paid_person.id
    person = result["person"]
    assert person is not None
    assert person["first_name"] == "Anon"
    assert person["last_name"] == "Tester"
    assert person["middle_name"] is None
    # PII from the paid tenant must NOT leak through.
    assert person["first_name"] != paid_person.first_name
    assert person["last_name"] != paid_person.last_name
    assert person["middle_name"] != paid_person.middle_name
    assert person["phone"] != paid_person.phone


@pytest.mark.asyncio
async def test_demo_create_candidate_does_not_409_on_email_seen_in_other_tenant(
    db: AsyncSession,
    paid_tenant_with_person: tuple[Tenant, User, Person],
    demo_tenant_with_user: tuple[Tenant, User],
) -> None:
    """Pre-fix: hitting an email that already had a candidate row in
    another tenant raised 409. After the fix the dedup branch is
    skipped for demo, so the second creation succeeds with a fresh
    Person scoped to the demo tenant.
    """
    paid, paid_user, paid_person = paid_tenant_with_person
    demo, demo_user = demo_tenant_with_user

    # First: paid tenant attaches a candidate with the registered email.
    base = {
        "first_name": "Real",
        "last_name": "Owner",
        "middle_name": None,
        "phone": None,
        "source": "manual",
        "notes": None,
    }
    paid_candidate = await recruitment_service.create_candidate(
        db,
        paid.id,
        user_id=paid_user.id,
        data=CandidateCreate(email=paid_person.email, **base),
    )

    # Second: demo tenant submits the same email. Pre-fix this raised
    # 409 ("This person is already a candidate in this tenant") because
    # the global Person lookup found paid's row. After the fix demo gets
    # a fresh Person and a separate Candidate row.
    demo_payload = CandidateCreate(
        email=paid_person.email,
        first_name="Anon",
        last_name="Tester",
        middle_name=None,
        phone=None,
        source="demo",
        notes=None,
    )
    demo_candidate = await recruitment_service.create_candidate(
        db, demo.id, user_id=demo_user.id, data=demo_payload
    )
    assert demo_candidate["person_id"] != paid_candidate["person_id"]
    assert demo_candidate["id"] != paid_candidate["id"]


@pytest.mark.asyncio
async def test_paid_tenant_create_candidate_still_dedupes_person(
    db: AsyncSession,
) -> None:
    """Regression guard: the demo skip must not widen to paid tenants."""
    paid_a, paid_a_user = await _make_tenant(db, is_demo=False)
    paid_b, paid_b_user = await _make_tenant(db, is_demo=False)

    email = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    base = {
        "first_name": "Real",
        "last_name": "User",
        "middle_name": None,
        "phone": None,
        "source": "manual",
        "notes": None,
    }
    first = await recruitment_service.create_candidate(
        db, paid_a.id, user_id=paid_a_user.id, data=CandidateCreate(email=email, **base)
    )
    second = await recruitment_service.create_candidate(
        db, paid_b.id, user_id=paid_b_user.id, data=CandidateCreate(email=email, **base)
    )
    assert second["person_id"] == first["person_id"]

    # Only one Person row for this email across the registry.
    rows = (
        await db.execute(select(Person.id).where(Person.email == email))
    ).scalars().all()
    assert len(rows) == 1
