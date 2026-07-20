"""Unit tests for recruitment module service layer."""

import uuid

import pytest
from app.models import Person
from app.modules.recruitment import service
from app.modules.recruitment.models import VacancyStage
from app.modules.recruitment.schemas import (
    CandidateCreate,
    CandidateUpdate,
    CandidateVacancyCreate,
    CandidateVacancyStatusUpdate,
    VacancyCloseData,
    VacancyCreate,
    VacancyProfileUpdate,
    VacancyStageCreate,
    VacancyStageUpdate,
    VacancyUpdate,
)
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# --------------- helpers ---------------


def _vacancy_data(suffix: str | None = None) -> VacancyCreate:
    s = suffix or uuid.uuid4().hex[:6]
    return VacancyCreate(
        title=f"Vacancy {s}",
        description=f"Description for {s}",
    )


def _candidate_data(suffix: str | None = None) -> CandidateCreate:
    s = suffix or uuid.uuid4().hex[:6]
    return CandidateCreate(
        first_name=f"First{s}",
        last_name=f"Last{s}",
        email=f"{s}@example.com",
        source="linkedin",
    )


# --------------- TestVacancyCRUD ---------------


class TestVacancyCRUD:
    async def test_create_vacancy(self, db: AsyncSession, tenant, user):
        data = _vacancy_data()
        result = await service.create_vacancy(db, tenant.id, user.id, data)

        assert result["title"] == data.title
        assert result["description"] == data.description
        assert result["status"] == "draft"
        assert result["owner_id"] == user.id
        assert "id" in result
        assert result["created_at"] is not None

    async def test_list_vacancies(self, db: AsyncSession, tenant, user):
        await service.create_vacancy(db, tenant.id, user.id, _vacancy_data("a1"))
        await service.create_vacancy(db, tenant.id, user.id, _vacancy_data("a2"))

        items, total = await service.list_vacancies(db, tenant.id)
        assert total >= 2
        assert len(items) >= 2

    async def test_list_vacancies_filter_by_status(
        self, db: AsyncSession, tenant, user
    ):
        # Create a draft vacancy
        await service.create_vacancy(db, tenant.id, user.id, _vacancy_data("draft1"))

        # Create a vacancy and change status to published
        v2 = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data("pub1"))
        await service.update_vacancy(
            db, tenant.id, v2["id"], VacancyUpdate(status="published")
        )

        draft_items, draft_total = await service.list_vacancies(
            db, tenant.id, status="draft"
        )
        pub_items, pub_total = await service.list_vacancies(
            db, tenant.id, status="published"
        )

        assert draft_total >= 1
        assert all(v["status"] == "draft" for v in draft_items)
        assert pub_total >= 1
        assert all(v["status"] == "published" for v in pub_items)

    async def test_get_vacancy(self, db: AsyncSession, tenant, user):
        created = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        result = await service.get_vacancy(db, tenant.id, created["id"])

        assert result["id"] == created["id"]
        assert result["title"] == created["title"]
        assert result["description"] == created["description"]
        assert result["status"] == "draft"

    async def test_get_vacancy_not_found(self, db: AsyncSession, tenant):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_vacancy(db, tenant.id, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_get_vacancy_exposes_assessment_scale(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        """HRP-348: the manager-assessment sheet resolves its scale from
        the vacancy read — ``response_model`` used to strip both fields,
        so the sheet always fell back to the tenant default scale and
        never saw the bound one."""
        from app.modules.recruitment import manager_assessment_service

        created = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        scale = await manager_assessment_service.ensure_default_scale(db, tenant.id)
        await manager_assessment_service.set_vacancy_scale(
            db, tenant.id, user.id, created["id"], scale.id
        )

        response = await auth_client.get(f"/api/recruitment/vacancies/{created['id']}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["assessment_scale_id"] == str(scale.id)
        # Snapshot is frozen on first score write — until then it must be
        # present (not stripped) and null.
        assert "assessment_scale_snapshot" in body
        assert body["assessment_scale_snapshot"] is None

    async def test_update_vacancy(self, db: AsyncSession, tenant, user):
        created = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        updated = await service.update_vacancy(
            db, tenant.id, created["id"], VacancyUpdate(title="Updated Title")
        )

        assert updated["title"] == "Updated Title"
        assert updated["id"] == created["id"]
        # Description should remain unchanged
        assert updated["description"] == created["description"]

    async def test_vacancy_read_returns_text_blocks(
        self, auth_client, db: AsyncSession, tenant, user
    ):
        """HRP-344: requirements/responsibilities/conditions were persisted
        but missing from ``VacancyRead`` and the serializer, so the form
        showed them empty right after save."""
        created = await service.create_vacancy(
            db,
            tenant.id,
            user.id,
            VacancyCreate(
                title="Vacancy HRP-344",
                requirements="5+ years of Python",
                responsibilities="Own the recruitment module",
                conditions="Remote, full-time",
            ),
        )
        assert created["requirements"] == "5+ years of Python"

        response = await auth_client.get(f"/api/recruitment/vacancies/{created['id']}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["requirements"] == "5+ years of Python"
        assert body["responsibilities"] == "Own the recruitment module"
        assert body["conditions"] == "Remote, full-time"

        updated = await service.update_vacancy(
            db,
            tenant.id,
            created["id"],
            VacancyUpdate(requirements="7+ years of Python"),
        )
        assert updated["requirements"] == "7+ years of Python"
        assert updated["responsibilities"] == "Own the recruitment module"
        assert updated["conditions"] == "Remote, full-time"

    async def test_close_vacancy(self, db: AsyncSession, tenant, user):
        created = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        closed = await service.close_vacancy(
            db,
            tenant.id,
            created["id"],
            VacancyCloseData(
                resolution="cancelled", close_reason="Position no longer needed"
            ),
        )

        assert closed["status"] == "closed"
        assert closed["close_resolution"] == "cancelled"
        assert closed["close_reason"] == "Position no longer needed"
        assert closed["closed_at"] is not None


# --------------- TestCandidateCRUD ---------------


class TestCandidateCRUD:
    async def test_create_candidate(self, db: AsyncSession, tenant, user):
        data = _candidate_data()
        result = await service.create_candidate(db, tenant.id, user.id, data)

        assert result["person"] is not None
        assert result["person"]["first_name"] == data.first_name
        assert result["person"]["last_name"] == data.last_name
        assert result["person"]["email"] == data.email
        assert result["source"] == "linkedin"
        assert "id" in result
        assert result["person_id"] is not None

    async def test_create_candidate_dedup(self, db: AsyncSession, tenant, user):
        s = uuid.uuid4().hex[:6]
        data = _candidate_data(s)
        await service.create_candidate(db, tenant.id, user.id, data)

        # Same email should raise 409
        data2 = CandidateCreate(
            first_name="Another",
            last_name="Person",
            email=data.email,
            source="hh",
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create_candidate(db, tenant.id, user.id, data2)
        assert exc_info.value.status_code == 409

    async def test_create_candidate_existing_person(
        self, db: AsyncSession, tenant, user
    ):
        # Create a person manually first
        email = f"existing-{uuid.uuid4().hex[:6]}@example.com"
        person = Person(first_name="Existing", last_name="Person", email=email)
        db.add(person)
        await db.commit()
        await db.refresh(person)

        # Create candidate with the same email — should link to existing person
        data = CandidateCreate(
            first_name="Different",
            last_name="Name",
            email=email,
            source="referral",
        )
        result = await service.create_candidate(db, tenant.id, user.id, data)

        # Should use existing person (same person_id)
        assert result["person_id"] == person.id
        # Person data reflects the existing person, not the new create data
        assert result["person"]["first_name"] == "Existing"
        assert result["person"]["last_name"] == "Person"

    async def test_list_candidates(self, db: AsyncSession, tenant, user):
        await service.create_candidate(db, tenant.id, user.id, _candidate_data())
        await service.create_candidate(db, tenant.id, user.id, _candidate_data())

        items, total = await service.list_candidates(db, tenant.id)
        assert total >= 2
        assert len(items) >= 2

    async def test_get_candidate(self, db: AsyncSession, tenant, user):
        created = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )
        result = await service.get_candidate(db, tenant.id, created["id"])

        assert result["id"] == created["id"]
        assert result["person"] is not None
        assert result["person"]["first_name"] == created["person"]["first_name"]

    async def test_update_candidate(self, db: AsyncSession, tenant, user):
        created = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )
        updated = await service.update_candidate(
            db,
            tenant.id,
            created["id"],
            CandidateUpdate(source="hh", notes="Updated notes"),
        )

        assert updated["source"] == "hh"
        assert updated["id"] == created["id"]


# --------------- TestCandidateVacancy ---------------


class TestCandidateVacancy:
    async def test_attach_candidate(self, db: AsyncSession, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        candidate = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )

        result = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=candidate["id"],
                vacancy_id=vacancy["id"],
            ),
        )

        assert result["candidate_id"] == candidate["id"]
        assert result["vacancy_id"] == vacancy["id"]
        assert result["status"] == "new"
        assert "id" in result

    async def test_attach_duplicate(self, db: AsyncSession, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        candidate = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )

        link_data = CandidateVacancyCreate(
            candidate_id=candidate["id"],
            vacancy_id=vacancy["id"],
        )
        await service.attach_candidate(db, tenant.id, user.id, link_data)

        # Duplicate attach should raise 409
        with pytest.raises(HTTPException) as exc_info:
            await service.attach_candidate(db, tenant.id, user.id, link_data)
        assert exc_info.value.status_code == 409

    async def test_change_status(self, db: AsyncSession, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        candidate = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )

        # Create a stage to move candidate to
        stage = await service.create_stage(
            db,
            tenant.id,
            VacancyStageCreate(name="Interview", code="interview", sort_order=2),
        )

        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=candidate["id"],
                vacancy_id=vacancy["id"],
            ),
        )

        updated = await service.change_candidate_status(
            db,
            tenant.id,
            cv["id"],
            CandidateVacancyStatusUpdate(
                stage_id=stage["id"], comment="Moving to interview"
            ),
        )

        assert updated["stage_id"] == stage["id"]
        assert len(updated["status_history"]) >= 1
        last_entry = updated["status_history"][-1]
        assert last_entry["to_stage_id"] == str(stage["id"])
        assert last_entry["comment"] == "Moving to interview"

    async def test_list_vacancy_candidates(self, db: AsyncSession, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        c1 = await service.create_candidate(db, tenant.id, user.id, _candidate_data())
        c2 = await service.create_candidate(db, tenant.id, user.id, _candidate_data())

        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=c1["id"], vacancy_id=vacancy["id"]),
        )
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(candidate_id=c2["id"], vacancy_id=vacancy["id"]),
        )

        items, total = await service.list_vacancy_candidates(
            db, tenant.id, vacancy["id"]
        )
        assert total == 2
        assert len(items) == 2
        candidate_ids = {item["candidate_id"] for item in items}
        assert c1["id"] in candidate_ids
        assert c2["id"] in candidate_ids


# --------------- TestFunnelStages ---------------


class TestFunnelStages:
    async def test_list_default_stages(self, db: AsyncSession, tenant):
        """List stages returns system defaults (tenant_id IS NULL) if they exist.

        If no system stages exist in the test DB (migrations not applied),
        this test verifies the listing endpoint works and returns a list.
        """
        stages = await service.list_stages(db, tenant.id)
        # Result is a list (possibly empty if no system stages seeded)
        assert isinstance(stages, list)

    async def test_create_tenant_stage(self, db: AsyncSession, tenant):
        data = VacancyStageCreate(
            name="Technical Interview",
            code="tech_interview",
            sort_order=5,
            is_terminal=False,
            color="#00ff00",
        )
        result = await service.create_stage(db, tenant.id, data)

        assert result["name"] == "Technical Interview"
        assert result["code"] == "tech_interview"
        assert result["sort_order"] == 5
        assert result["is_terminal"] is False
        assert result["color"] == "#00ff00"
        assert result["tenant_id"] == tenant.id
        assert result["vacancy_id"] is None

        # Verify it appears in list
        stages = await service.list_stages(db, tenant.id)
        assert any(s["id"] == result["id"] for s in stages)

    async def test_update_stage(self, db: AsyncSession, tenant):
        created = await service.create_stage(
            db,
            tenant.id,
            VacancyStageCreate(name="Old Name", code="old_code", sort_order=1),
        )
        updated = await service.update_stage(
            db, tenant.id, created["id"], VacancyStageUpdate(name="New Name")
        )

        assert updated["name"] == "New Name"
        assert updated["code"] == "old_code"  # unchanged
        assert updated["id"] == created["id"]

    async def test_delete_stage(self, db: AsyncSession, tenant):
        created = await service.create_stage(
            db,
            tenant.id,
            VacancyStageCreate(name="To Delete", code="del_me", sort_order=99),
        )
        stage_id = created["id"]

        await service.delete_stage(db, tenant.id, stage_id)

        # Verify it is gone from the list
        stages = await service.list_stages(db, tenant.id)
        assert not any(s["id"] == stage_id for s in stages)

    async def test_cannot_delete_system_stage(self, db: AsyncSession, tenant):
        """System stages (tenant_id IS NULL) cannot be deleted."""
        # Create a system-level stage directly (tenant_id=None)
        system_stage = VacancyStage(
            tenant_id=None,
            vacancy_id=None,
            name="System Stage",
            code="system_test",
            sort_order=0,
            is_terminal=False,
        )
        db.add(system_stage)
        await db.commit()
        await db.refresh(system_stage)

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_stage(db, tenant.id, system_stage.id)
        assert exc_info.value.status_code == 403


# --------------- TestProfileService ---------------


class TestProfileService:
    async def test_save_profile(self, db: AsyncSession, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        profile_data = {"competences": [{"name": "Python", "criticality": "critical"}]}
        result = await service.save_profile(
            db,
            tenant.id,
            vacancy["id"],
            VacancyProfileUpdate(profile_data=profile_data),
        )

        assert result["vacancy_id"] == vacancy["id"]
        assert result["version"] == 1
        saved = result["profile_data"]["competences"][0]
        assert saved["name"] == "Python"
        assert saved["criticality"] == "critical"
        # HRP-348: manual saves normalize competence ids exactly like the
        # generate path, so assessment sheets stay keyed consistently.
        assert saved["id"] == str(service.normalize_competence_id("Python"))

    async def test_save_profile_increments_version(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        data_v1 = {"competences": [{"name": "Python"}]}
        result_v1 = await service.save_profile(
            db, tenant.id, vacancy["id"], VacancyProfileUpdate(profile_data=data_v1)
        )
        assert result_v1["version"] == 1

        data_v2 = {"competences": [{"name": "Python"}, {"name": "FastAPI"}]}
        result_v2 = await service.save_profile(
            db, tenant.id, vacancy["id"], VacancyProfileUpdate(profile_data=data_v2)
        )
        assert result_v2["version"] == 2
        assert [c["name"] for c in result_v2["profile_data"]["competences"]] == [
            "Python",
            "FastAPI",
        ]
        # Same profile row, same vacancy
        assert result_v2["id"] == result_v1["id"]

    async def test_save_profile_stale_base_version_conflicts(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-339: a stale inline-edit draft must not overwrite a profile
        that moved on (generation applied in another tab, concurrent save)."""
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        v1 = await service.save_profile(
            db,
            tenant.id,
            vacancy["id"],
            VacancyProfileUpdate(profile_data={"competences": [{"name": "A"}]}),
        )
        # Another session bumps the profile to v2.
        await service.save_profile(
            db,
            tenant.id,
            vacancy["id"],
            VacancyProfileUpdate(
                profile_data={"competences": [{"name": "B"}]},
                base_version=v1["version"],
            ),
        )
        # The stale editor still holds v1 — its save is rejected.
        with pytest.raises(HTTPException) as exc:
            await service.save_profile(
                db,
                tenant.id,
                vacancy["id"],
                VacancyProfileUpdate(
                    profile_data={"competences": [{"name": "C"}]},
                    base_version=v1["version"],
                ),
            )
        assert exc.value.status_code == 409
        # Matching version (or omitted base_version, for older clients)
        # still saves.
        current = await service.save_profile(
            db,
            tenant.id,
            vacancy["id"],
            VacancyProfileUpdate(
                profile_data={"competences": [{"name": "D"}]},
                base_version=2,
            ),
        )
        assert current["version"] == 3

    async def test_save_profile_keeps_uuid_ids_and_normalizes_slugs(
        self, db: AsyncSession, tenant, user
    ):
        """HRP-348: PUT /profile assigns stable uuid5 ids to competences
        added manually (no id / slug id), and passes real UUIDs through."""
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())

        existing_id = str(uuid.uuid4())
        profile_data = {
            "competences": [
                {"id": existing_id, "name": "Kept"},
                {"id": "python-skills", "name": "Python"},
                {"name": "Teamwork"},
            ]
        }
        result = await service.save_profile(
            db,
            tenant.id,
            vacancy["id"],
            VacancyProfileUpdate(profile_data=profile_data),
        )

        comps = result["profile_data"]["competences"]
        assert comps[0]["id"] == existing_id
        assert comps[1]["id"] == str(service.normalize_competence_id("python-skills"))
        assert comps[2]["id"] == str(service.normalize_competence_id("Teamwork"))


# --------------- TestNormalizeCompetenceId (R2c) ---------------


class TestNormalizeCompetenceId:
    def test_returns_none_for_empty(self):
        assert service.normalize_competence_id(None) is None
        assert service.normalize_competence_id("") is None
        assert service.normalize_competence_id("   ") is None

    def test_passthrough_when_uuid(self):
        u = uuid.uuid4()
        assert service.normalize_competence_id(u) == u
        assert service.normalize_competence_id(str(u)) == u

    def test_slug_is_deterministic(self):
        a = service.normalize_competence_id("senior-python-skills")
        b = service.normalize_competence_id("senior-python-skills")
        c = service.normalize_competence_id("teamwork")
        assert a == b
        assert a != c
        assert isinstance(a, uuid.UUID)


# --------------- TestRecruitmentInvites (FR-20) ---------------


class TestRecruitmentInvites:
    async def _setup_cv(self, db: AsyncSession, tenant, user):
        from app.modules.recruitment.schemas import InviteCreate

        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        candidate = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )
        cv = await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=candidate["id"], vacancy_id=vacancy["id"]
            ),
        )
        return vacancy, candidate, cv, InviteCreate

    async def test_create_invite_persists_token(self, db, tenant, user):
        from unittest.mock import patch

        vacancy, candidate, cv, InviteCreate = await self._setup_cv(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            inv = await service.create_assessment_invite(
                db,
                tenant.id,
                cv["id"],
                InviteCreate(email="ext@example.com", evaluator_name="Ext"),
            )
        assert inv["status"] == "pending"
        assert len(inv["token"]) > 20
        assert inv["email"] == "ext@example.com"

    async def test_get_invite_by_token_marks_opened(self, db, tenant, user):
        from unittest.mock import patch

        _, _, cv, InviteCreate = await self._setup_cv(db, tenant, user)
        with patch("app.core.email.enqueue_email"):
            inv = await service.create_assessment_invite(
                db,
                tenant.id,
                cv["id"],
                InviteCreate(email="e@example.com"),
            )
        fetched = await service.get_invite_by_token(db, inv["token"])
        assert fetched is not None
        assert fetched["status"] == "opened"

    async def test_record_invite_assessment_writes_audit_row(self, db, tenant, user):
        """FR-28: invite submission must leave an audit row even though
        the function takes a token rather than tenant_id."""
        from unittest.mock import patch

        from app.modules.recruitment import audit_service

        vacancy, _, cv, InviteCreate = await self._setup_cv(db, tenant, user)
        await service.save_profile(
            db,
            tenant.id,
            vacancy["id"],
            VacancyProfileUpdate(
                profile_data={
                    "competences": [{"id": "communication", "name": "Communication"}]
                }
            ),
        )
        with patch("app.core.email.enqueue_email"):
            inv = await service.create_assessment_invite(
                db,
                tenant.id,
                cv["id"],
                InviteCreate(email="e@example.com"),
            )

        competence_uuid = service.normalize_competence_id("communication")
        result = await service.record_invite_assessment(
            db,
            inv["token"],
            {
                "candidate_vacancy_id": cv["id"],
                "competence_id": str(competence_uuid),
                "score": 4.5,
                "comment": "Solid",
            },
        )

        items, _ = await audit_service.list_events(
            db, tenant.id, action="assessment.invite_submit"
        )
        assert items, "assessment.invite_submit audit row not found"
        row = items[0]
        assert row["entity_type"] == "assessment"
        assert row["entity_id"] == result["id"]
        assert row["user_id"] is None  # external evaluator, anonymous
        assert row["payload_diff"]["invite_id"] == str(inv["id"])

    async def test_record_invite_assessment_blocks_unknown_competence(
        self, db, tenant, user
    ):
        from unittest.mock import patch

        vacancy, _, cv, InviteCreate = await self._setup_cv(db, tenant, user)
        # Save a profile with one competence so unrelated UUIDs are rejected
        await service.save_profile(
            db,
            tenant.id,
            vacancy["id"],
            VacancyProfileUpdate(
                profile_data={
                    "competences": [{"id": "communication", "name": "Communication"}]
                }
            ),
        )
        with patch("app.core.email.enqueue_email"):
            inv = await service.create_assessment_invite(
                db,
                tenant.id,
                cv["id"],
                InviteCreate(email="e@example.com"),
            )
        with pytest.raises(HTTPException) as exc:
            await service.record_invite_assessment(
                db,
                inv["token"],
                {
                    "candidate_vacancy_id": cv["id"],
                    "competence_id": str(uuid.uuid4()),  # not in profile
                    "score": 4.0,
                },
            )
        assert exc.value.status_code == 400


# --------------- TestResumeQueries (R1 closeouts) ---------------


class TestResumeQueries:
    async def test_list_candidate_resumes_empty(self, db, tenant, user):
        candidate = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )
        result = await service.list_candidate_resumes(db, tenant.id, candidate["id"])
        assert result == []

    async def test_list_candidate_vacancies(self, db, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        candidate = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )
        await service.attach_candidate(
            db,
            tenant.id,
            user.id,
            CandidateVacancyCreate(
                candidate_id=candidate["id"], vacancy_id=vacancy["id"]
            ),
        )
        result = await service.list_candidate_vacancies(db, tenant.id, candidate["id"])
        assert len(result) == 1
        assert result[0]["vacancy_id"] == vacancy["id"]


# --------------- TestPdfExport (FR-13/SCR-65) ---------------


class TestPdfExport:
    async def test_export_questions_pdf_renders_minimal(self, db, tenant, user):
        vacancy = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        candidate = await service.create_candidate(
            db, tenant.id, user.id, _candidate_data()
        )
        pdf = await service.export_questions_pdf(
            db, tenant.id, candidate["id"], vacancy["id"]
        )
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")


# --------------- TestRouteRegistration (HRP-134) ---------------


class TestRouteRegistration:
    def test_generate_profile_route_url(self):
        from app.modules.recruitment.router import router

        # FastAPI >= 0.139 keeps included routers nested in .routes (as
        # _IncludedRouter wrapping the original), so collect paths recursively.
        def collect_paths(routes):
            paths = set()
            for r in routes:
                if hasattr(r, "path"):
                    paths.add(r.path)
                nested = getattr(r, "routes", None) or getattr(
                    getattr(r, "original_router", None), "routes", []
                )
                paths.update(collect_paths(nested))
            return paths

        assert "/recruitment/vacancies/{vacancy_id}/profile/generate" in collect_paths(
            router.routes
        )


# --------------- TestHiringManager (HRP-360) ---------------


async def _make_tenant_user(
    db: AsyncSession, tenant_id, *, first_name="Jane", last_name="Manager", role=None
):
    from app.modules.auth.models import User, user_roles
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    u = User(
        email=f"hm-{uuid.uuid4().hex[:8]}@test.com",
        password_hash="x",
        first_name=first_name,
        last_name=last_name,
        tenant_id=tenant_id,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    if role is not None:
        await db.execute(user_roles.insert().values(user_id=u.id, role_id=role.id))
        await db.commit()
    # Expunge before re-selecting — otherwise the identity map returns the
    # cached instance whose roles collection was loaded before the insert.
    user_id = u.id
    db.expunge(u)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    return result.scalar_one()


class TestHiringManager:
    async def test_create_defaults_to_creator(self, db: AsyncSession, tenant, user):
        v = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        assert v["hiring_manager_id"] == user.id
        assert v["hiring_manager_name"] == "Test User"

    async def test_create_with_explicit_admin(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        other = await _make_tenant_user(db, tenant.id, role=admin_role)
        data = _vacancy_data()
        data.hiring_manager_id = other.id
        v = await service.create_vacancy(db, tenant.id, user.id, data)
        assert v["hiring_manager_id"] == other.id
        assert v["hiring_manager_name"] == "Jane Manager"

    async def test_create_rejects_non_admin(self, db: AsyncSession, tenant, user):
        no_role = await _make_tenant_user(db, tenant.id)
        data = _vacancy_data()
        data.hiring_manager_id = no_role.id
        with pytest.raises(HTTPException) as exc_info:
            await service.create_vacancy(db, tenant.id, user.id, data)
        assert exc_info.value.status_code == 422

    async def test_create_by_non_admin_leaves_default_empty(
        self, db: AsyncSession, tenant, user
    ):
        """A creator without an admin-tier role must not become the hiring
        manager by default — the picker could never display them."""
        no_role = await _make_tenant_user(db, tenant.id)
        v = await service.create_vacancy(db, tenant.id, no_role.id, _vacancy_data())
        assert v["hiring_manager_id"] is None

    async def test_create_rejects_foreign_tenant_user(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        from app.modules.company.models import Tenant

        other_tenant = Tenant(
            name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
        )
        db.add(other_tenant)
        await db.commit()
        await db.refresh(other_tenant)
        foreign = await _make_tenant_user(db, other_tenant.id, role=admin_role)
        data = _vacancy_data()
        data.hiring_manager_id = foreign.id
        with pytest.raises(HTTPException) as exc_info:
            await service.create_vacancy(db, tenant.id, user.id, data)
        assert exc_info.value.status_code == 422

    async def test_update_changes_hiring_manager(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        other = await _make_tenant_user(db, tenant.id, role=admin_role)
        created = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        updated = await service.update_vacancy(
            db,
            tenant.id,
            created["id"],
            VacancyUpdate(hiring_manager_id=other.id),
        )
        assert updated["hiring_manager_id"] == other.id
        assert updated["hiring_manager_name"] == "Jane Manager"

    async def test_list_hiring_manager_options(
        self, db: AsyncSession, tenant, user, admin_role
    ):
        admin2 = await _make_tenant_user(db, tenant.id, role=admin_role)
        no_role = await _make_tenant_user(
            db, tenant.id, first_name="No", last_name="Role"
        )
        options = await service.list_hiring_manager_options(db, tenant.id)
        ids = {o["id"] for o in options}
        assert user.id in ids
        assert admin2.id in ids
        assert no_role.id not in ids


# --------------- TestVacancyListJoinedFields (HRP-363) ---------------


class TestVacancyListJoinedFields:
    async def test_list_populates_owner_name(self, db: AsyncSession, tenant, user):
        await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        items, _ = await service.list_vacancies(db, tenant.id)
        assert all(v["owner_name"] == "Test User" for v in items)

    async def test_list_populates_division_name(self, db: AsyncSession, tenant, user):
        from app.modules.company.models import Division

        division = Division(tenant_id=tenant.id, name="Engineering")
        db.add(division)
        await db.commit()
        await db.refresh(division)

        data = _vacancy_data()
        data.division_id = division.id
        created = await service.create_vacancy(db, tenant.id, user.id, data)

        items, _ = await service.list_vacancies(db, tenant.id)
        row = next(v for v in items if v["id"] == created["id"])
        assert row["division_name"] == "Engineering"

    async def test_list_include_archived(self, db: AsyncSession, tenant, user):
        created = await service.create_vacancy(db, tenant.id, user.id, _vacancy_data())
        await service.archive_vacancy(db, tenant.id, user.id, created["id"])

        default_items, _ = await service.list_vacancies(db, tenant.id)
        assert created["id"] not in {v["id"] for v in default_items}

        all_items, _ = await service.list_vacancies(
            db, tenant.id, include_archived=True
        )
        assert created["id"] in {v["id"] for v in all_items}
