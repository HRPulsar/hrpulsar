"""HRP-504: the vacancy Questions tab reads the live question sets.

Two defects, one root: the tab was wired to storage nothing writes any
more. It listed the legacy ``candidate_questions`` rows (the candidate
page has written ``question_sets``/``questions`` since HRP-205), took its
candidate names from an endpoint that only knew HR ``Person`` rows — so
resume-sourced candidates rendered as raw UUIDs — and built its
competence filter from raw profile slugs, which never match the uuid5
keys stored on a question.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from app.modules.recruitment import question_service, service
from app.modules.recruitment.common import normalize_competence_id
from app.modules.recruitment.models import Question, QuestionSet, VacancyProfile
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateVacancyCreate,
    VacancyCreate,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

# Slug-keyed, exactly as the generator writes an AI-authored profile.
PROFILE = [
    {"id": "python-skills", "name": "Python"},
    {"id": "system-design", "name": "System design"},
    {"id": "communication", "name": "Communication"},
]


async def _vacancy(db: AsyncSession, tenant, user) -> uuid.UUID:
    vac = await service.create_vacancy(
        db, tenant.id, user.id, VacancyCreate(title=f"V {uuid.uuid4().hex[:5]}")
    )
    vacancy_id = uuid.UUID(str(vac["id"]))
    db.add(
        VacancyProfile(
            tenant_id=tenant.id,
            vacancy_id=vacancy_id,
            profile_data={"competences": PROFILE},
        )
    )
    await db.commit()
    return vacancy_id


async def _candidate(
    db: AsyncSession, tenant, user, vacancy_id: uuid.UUID, *, full_name: str
) -> uuid.UUID:
    """A resume-sourced candidate: full_name only, no Person row."""
    first, last = full_name.split(" ", 1)
    cand = await service.create_candidate(
        db,
        tenant.id,
        user.id,
        CandidateCreate(
            first_name=first,
            last_name=last,
            email=f"{uuid.uuid4().hex[:6]}@example.com",
        ),
    )
    cv = await service.attach_candidate(
        db,
        tenant.id,
        user.id,
        CandidateVacancyCreate(
            candidate_id=uuid.UUID(str(cand["id"])),
            vacancy_id=vacancy_id,
        ),
    )
    return uuid.UUID(str(cv["id"]))


async def _tenant_user_with_role(db: AsyncSession, tenant, role_code: str):
    """An ordinary member of the tenant holding exactly one role."""
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.modules.auth.models import Role, user_roles
    from app.modules.auth.models import User as AuthUser
    from sqlalchemy import select

    role = (
        await db.execute(select(Role).where(Role.code == role_code))
    ).scalars().first()
    if role is None:
        role = Role(name=role_code.title(), code=role_code, is_system=True)
        db.add(role)
        await db.commit()
        await db.refresh(role)
    member = AuthUser(
        email=f"{role_code}-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("testpass123"),
        first_name="Plain",
        last_name="Member",
        tenant_id=tenant.id,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    await db.execute(user_roles.insert().values(user_id=member.id, role_id=role.id))
    await db.commit()
    return member


async def _question_set(
    db: AsyncSession,
    tenant,
    cv_id: uuid.UUID,
    *,
    name: str,
    competence_slugs: list[str | None],
    archived: bool = False,
) -> QuestionSet:
    from datetime import datetime, timezone

    qs = QuestionSet(
        tenant_id=tenant.id,
        candidate_vacancy_id=cv_id,
        set_type="interview_round",
        name=name,
        status="ready",
        generation_mode="initial",
        archived_at=datetime.now(timezone.utc) if archived else None,
    )
    db.add(qs)
    await db.flush()
    for idx, slug in enumerate(competence_slugs):
        db.add(
            Question(
                tenant_id=tenant.id,
                question_set_id=qs.id,
                text=f"{name} Q{idx}",
                goal="verify_skill",
                priority="must_ask",
                competence_id=normalize_competence_id(slug) if slug else None,
                sort_order=idx,
                source="ai_generated",
                status="active",
            )
        )
    await db.commit()
    await db.refresh(qs)
    return qs


class TestVacancyQuestionSets:
    async def test_returns_candidate_names_not_uuids(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _candidate(db, tenant, user, vacancy_id, full_name="Ada Lovelace")
        await _question_set(
            db, tenant, cv_id, name="Interview 1", competence_slugs=["python-skills"]
        )

        payload = await question_service.list_vacancy_question_sets(
            db, tenant.id, vacancy_id
        )
        assert [c["candidate_name"] for c in payload["candidates"]] == ["Ada Lovelace"]

    async def test_offers_every_vacancy_competence(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """The filter lists the whole profile, not just what got asked."""
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _candidate(db, tenant, user, vacancy_id, full_name="Grace Hopper")
        await _question_set(
            db, tenant, cv_id, name="Interview 1", competence_slugs=["python-skills"]
        )

        payload = await question_service.list_vacancy_question_sets(
            db, tenant.id, vacancy_id
        )
        assert [c["name"] for c in payload["competences"]] == [
            "Python",
            "System design",
            "Communication",
        ]
        # Slug-keyed profile, uuid5-keyed questions — the ids must agree.
        assert payload["competences"][0]["id"] == normalize_competence_id(
            "python-skills"
        )

    async def test_questions_carry_the_resolved_competence_name(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _candidate(db, tenant, user, vacancy_id, full_name="Alan Turing")
        await _question_set(
            db,
            tenant,
            cv_id,
            name="Interview 1",
            competence_slugs=["system-design", None],
        )

        payload = await question_service.list_vacancy_question_sets(
            db, tenant.id, vacancy_id
        )
        questions = payload["candidates"][0]["question_set"]["questions"]
        assert [q["competence_name"] for q in questions] == ["System design", None]

    async def test_only_the_latest_live_set_is_returned(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _candidate(db, tenant, user, vacancy_id, full_name="Edsger D")
        await _question_set(
            db, tenant, cv_id, name="Interview 1", competence_slugs=["python-skills"]
        )
        latest = await _question_set(
            db, tenant, cv_id, name="Interview 2", competence_slugs=["communication"]
        )

        payload = await question_service.list_vacancy_question_sets(
            db, tenant.id, vacancy_id
        )
        question_set = payload["candidates"][0]["question_set"]
        assert question_set["id"] == latest.id
        assert question_set["name"] == "Interview 2"

    async def test_archived_sets_are_skipped(
        self, db: AsyncSession, tenant, user
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _candidate(db, tenant, user, vacancy_id, full_name="Barbara L")
        await _question_set(
            db,
            tenant,
            cv_id,
            name="Interview 1",
            competence_slugs=["python-skills"],
            archived=True,
        )

        payload = await question_service.list_vacancy_question_sets(
            db, tenant.id, vacancy_id
        )
        assert payload["candidates"][0]["question_set"] is None

    async def test_candidate_without_questions_still_appears(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """The candidate filter must list everyone on the vacancy."""
        vacancy_id = await _vacancy(db, tenant, user)
        await _candidate(db, tenant, user, vacancy_id, full_name="Katherine J")

        payload = await question_service.list_vacancy_question_sets(
            db, tenant.id, vacancy_id
        )
        assert len(payload["candidates"]) == 1
        assert payload["candidates"][0]["question_set"] is None

    async def test_unknown_vacancy_404s(self, db: AsyncSession, tenant) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await question_service.list_vacancy_question_sets(
                db, tenant.id, uuid.uuid4()
            )
        assert exc.value.status_code == 404


class TestPlainCandidateListing:
    async def test_candidate_name_falls_back_to_full_name(
        self, db: AsyncSession, tenant, user
    ) -> None:
        """The endpoint the tab used to read from returned NULL names for
        every candidate without an HR Person row — the uuid symptom."""
        vacancy_id = await _vacancy(db, tenant, user)
        await _candidate(db, tenant, user, vacancy_id, full_name="Ada Lovelace")

        items, total = await service.list_vacancy_candidates(db, tenant.id, vacancy_id)
        assert total == 1
        assert items[0]["candidate_name"] == "Ada Lovelace"


class TestVacancyQuestionSetsRoute:
    """The route has to answer on the URL the frontend actually calls.

    Review finding: the endpoint was first published without the
    ``/recruitment`` segment every sibling route spells out (the
    aggregator router carries no prefix), so it served
    /api/vacancies/... while the tab called /api/recruitment/vacancies/...
    Every request 404'd and the tab showed its empty state forever. A
    string pinned in a frontend test cannot catch that — this one takes
    the URL out of the component source and calls it for real.
    """

    FRONTEND_TAB = (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "components"
        / "recruitment"
        / "vacancy-questions-tab.tsx"
    )

    def _frontend_path(self) -> str:
        source = self.FRONTEND_TAB.read_text(encoding="utf-8")
        match = re.search(r"api\.get<VacancyQuestionsPayload>\(\s*`([^`]+)`", source)
        assert match, "the tab no longer fetches its payload from a template literal"
        # `${vacancyId}` is the only interpolation in the template.
        return match.group(1).replace("${vacancyId}", "{vacancy_id}")

    async def test_frontend_url_is_served(
        self, db: AsyncSession, tenant, user, auth_client
    ) -> None:
        vacancy_id = await _vacancy(db, tenant, user)
        cv_id = await _candidate(db, tenant, user, vacancy_id, full_name="Ada Lovelace")
        await _question_set(
            db, tenant, cv_id, name="Interview 1", competence_slugs=["python-skills"]
        )

        url = "/api" + self._frontend_path().replace("{vacancy_id}", str(vacancy_id))
        response = await auth_client.get(url)

        assert response.status_code == 200, response.text
        body = response.json()
        assert [c["candidate_name"] for c in body["candidates"]] == ["Ada Lovelace"]
        assert [c["name"] for c in body["competences"]] == [
            "Python",
            "System design",
            "Communication",
        ]
        questions = body["candidates"][0]["question_set"]["questions"]
        assert questions[0]["competence_name"] == "Python"

    async def test_route_is_registered_under_the_recruitment_prefix(self) -> None:
        from app.main import app

        paths = {getattr(route, "path", None) for route in app.routes}
        assert "/api" + self._frontend_path() in paths

    async def test_plain_employee_cannot_enumerate_the_roster(
        self, db: AsyncSession, tenant, user, client
    ) -> None:
        """The payload is the whole roster — same gate as /candidates/enriched."""
        from app.core.security import create_access_token

        vacancy_id = await _vacancy(db, tenant, user)
        employee = await _tenant_user_with_role(db, tenant, "employee")
        client.headers["Authorization"] = (
            f"Bearer {create_access_token(str(employee.id), str(tenant.id))}"
        )

        response = await client.get(
            f"/api/recruitment/vacancies/{vacancy_id}/question-sets"
        )
        assert response.status_code == 403
