"""HRP-181 REDO Stage 2 — canonical candidate endpoints.

Covers FR-04 (manual add + duplicate-detect + soft-delete + re-import),
FR-08 (per-vacancy stage override), FR-09 (enriched list with
``score_divergence`` + terminal-stage sort + ETag-gated PATCH), and the
full-card payload that drives the candidate detail page.

The tests drive the service layer directly when they need to assert on
ORM state and the HTTP layer via ``auth_client`` when they need to verify
status codes / headers / response shape.
"""

from __future__ import annotations

import uuid

import pytest
from app.core.errors import AppError
from app.modules.recruitment import service
from app.modules.recruitment.models import (
    Candidate,
    CandidateFile,
    CandidateVacancy,
    VacancyStage,
)
from app.modules.recruitment.schemas import (
    BatchFinalizeFile,
    BatchFinalizeRequest,
    CandidateCanonicalPatch,
    CandidateManualCreate,
    CandidateVacancyPatch,
    VacancyCreate,
    VacancyStageReplaceItem,
    VacancyStagesReplace,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_vacancy(db: AsyncSession, tenant_id, user_id, title: str = "V"):
    # Seed the tenant funnel so the new attachment lands on a real stage.
    await service.seed_default_recruitment_stages(db, tenant_id)
    await db.commit()
    return await service.create_vacancy(
        db, tenant_id, user_id, VacancyCreate(title=f"{title}-{uuid.uuid4().hex[:6]}")
    )


def _manual_payload(**overrides) -> CandidateManualCreate:
    base = {
        "full_name": "Alice Smith",
        "email": f"alice-{uuid.uuid4().hex[:6]}@example.com",
    }
    base.update(overrides)
    return CandidateManualCreate(**base)


# ---------------------------------------------------------------------------
# Manual add
# ---------------------------------------------------------------------------


class TestManualAdd:
    async def test_creates_candidate_and_attaches_to_first_active_stage(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        payload = _manual_payload(
            full_name="Alice Smith",
            email="alice@example.com",
            current_position="Senior Engineer",
            years_of_experience=8,
        )
        result = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], payload
        )

        assert result["full_name"] == "Alice Smith"
        assert result["email"] == "alice@example.com"
        assert "candidate_vacancy_id" in result
        assert result["etag"].startswith('W/"')

        cv = (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.id == result["candidate_vacancy_id"]
                )
            )
        ).scalar_one()
        assert cv.tenant_id == tenant.id
        assert cv.candidate_id == result["id"]
        assert cv.vacancy_id == vacancy["id"]
        # First active stage = "new" with sort_order=10.
        stage = (
            await db.execute(
                select(VacancyStage).where(VacancyStage.id == cv.stage_id)
            )
        ).scalar_one()
        assert stage.code == "new"
        assert stage.stage_type == "active"

    async def test_requires_email_or_phone(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        with pytest.raises(HTTPException) as exc:
            await service.add_candidate_to_vacancy_manual(
                db,
                tenant.id,
                user.id,
                vacancy["id"],
                CandidateManualCreate(full_name="No Contact"),
            )
        assert exc.value.status_code == 422

    async def test_duplicate_email_returns_existing_id(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload(
                full_name="Anna", email="anna@example.com"
            )
        )

        vacancy2 = await _make_vacancy(db, tenant.id, user.id, "V2")
        with pytest.raises(AppError) as exc:
            await service.add_candidate_to_vacancy_manual(
                db,
                tenant.id,
                user.id,
                vacancy2["id"],
                CandidateManualCreate(
                    full_name="Anna duplicate",
                    email="ANNA@example.com",
                ),
            )
        assert exc.value.status_code == 409
        # i18n F3: the object-shaped detail is rendered by the handler from
        # ``code`` + ``detail_extra``; the wire shape is unchanged.
        assert exc.value.code == "candidate_email_conflict"
        assert "existing_candidate_id" in exc.value.detail_extra

    async def test_duplicate_against_archived_is_allowed(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        first = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload(
                full_name="Bob", email="bob@example.com"
            )
        )
        await service.archive_candidate(db, tenant.id, first["id"])

        vacancy2 = await _make_vacancy(db, tenant.id, user.id, "V2")
        second = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy2["id"],
            CandidateManualCreate(full_name="Bob v2", email="bob@example.com"),
        )
        assert second["id"] != first["id"]
        assert second["email"] == "bob@example.com"


# ---------------------------------------------------------------------------
# Batch finalize (from-parsed)
# ---------------------------------------------------------------------------


class TestFromParsed:
    async def test_link_existing_and_create_new(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)

        # Existing canonical candidate that the client wants to link to.
        existing = Candidate(
            tenant_id=tenant.id,
            full_name="Existing",
            email="existing@example.com",
        )
        db.add(existing)
        await db.flush()

        # Two parsed files. file_a has link_candidate_id set; file_b is
        # parsed-only (new candidate from parsed_data).
        file_a = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=existing.id,
            original_filename="a.pdf",
            mime_type="application/pdf",
            file_size=1024,
            parse_status="completed",
            parsed_data={
                "first_name": "Existing",
                "last_name": "",
                "contacts": {"email": "existing@example.com"},
            },
        )
        # Use a temporary candidate row for file_b so the FK is valid before
        # finalize re-points it (parser writes the file under a placeholder
        # Candidate).
        placeholder = Candidate(
            tenant_id=tenant.id,
            full_name="placeholder",
            email=None,
        )
        db.add(placeholder)
        await db.flush()
        file_b = CandidateFile(
            tenant_id=tenant.id,
            candidate_id=placeholder.id,
            original_filename="b.pdf",
            mime_type="application/pdf",
            file_size=1024,
            parse_status="completed",
            parsed_data={
                "first_name": "Fresh",
                "last_name": "Lead",
                "contacts": {"email": "fresh@example.com", "phone": "+123"},
                "experience": [{"position": "Senior PM"}],
            },
        )
        db.add_all([file_a, file_b])
        await db.commit()

        result = await service.finalize_candidates_from_parsed(
            db,
            tenant.id,
            user.id,
            vacancy["id"],
            BatchFinalizeRequest(
                files=[
                    BatchFinalizeFile(
                        file_id=file_a.id, link_candidate_id=existing.id
                    ),
                    BatchFinalizeFile(file_id=file_b.id),
                ]
            ),
        )

        assert {item["file_id"] for item in result["linked"]} == {str(file_a.id)}
        assert {item["file_id"] for item in result["created"]} == {str(file_b.id)}
        assert result["skipped"] == []

        # Two CandidateVacancy rows on the vacancy now: existing + new.
        cvs = (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.vacancy_id == vacancy["id"]
                )
            )
        ).scalars().all()
        assert len(cvs) == 2


# ---------------------------------------------------------------------------
# Enriched list
# ---------------------------------------------------------------------------


class TestEnrichedList:
    async def test_last_position_and_score_divergence(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)

        # Candidate with parsed experience.
        cand = Candidate(
            tenant_id=tenant.id,
            full_name="Charlie",
            email="charlie@example.com",
            parsed_resume_jsonb={
                "experience": [
                    {"position": "Staff Engineer", "company": "Acme"},
                    {"position": "Senior Engineer", "company": "Old"},
                ]
            },
            years_of_experience=12,
        )
        db.add(cand)
        await db.flush()

        cv = CandidateVacancy(
            tenant_id=tenant.id,
            candidate_id=cand.id,
            vacancy_id=vacancy["id"],
            stage_id=await service._first_non_terminal_stage_id(
                db, tenant.id, vacancy["id"]
            ),
            status="new",
            manager_score=4.0,
            ai_score=0.5,  # canonical 0..1 raw (HRP-274)
            # Divergence compares the tenant-scale normalized value:
            # 4.0 vs 2.5 → delta 1.5 ≥ 1.0 threshold.
            ai_score_normalized=2.5,
        )
        db.add(cv)
        await db.commit()

        items, total = await service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy["id"]
        )
        assert total == 1
        row = items[0]
        assert row["last_position"] == "Staff Engineer"
        assert row["years_of_experience"] == 12
        assert row["score_divergence"] is True
        assert row["manager_score"] == 4.0
        assert row["ai_score"] == 0.5
        assert row["ai_score_normalized"] == 2.5
        assert row["ai_verdict"] == "pending"
        assert row["stage"]["code"] == "new"

    async def test_sort_pushes_terminal_to_bottom(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        stages = await service._get_applicable_stages(
            db, tenant.id, vacancy["id"]
        )
        active = next(s for s in stages if s.code == "new")
        rejected = next(s for s in stages if s.code == "rejected")

        c1 = Candidate(tenant_id=tenant.id, full_name="C1", email="c1@e.x")
        c2 = Candidate(tenant_id=tenant.id, full_name="C2", email="c2@e.x")
        c3 = Candidate(tenant_id=tenant.id, full_name="C3", email="c3@e.x")
        db.add_all([c1, c2, c3])
        await db.flush()

        # Two active with different manager_scores; one terminal.
        db.add(CandidateVacancy(
            tenant_id=tenant.id, candidate_id=c1.id, vacancy_id=vacancy["id"],
            stage_id=active.id, status="new", manager_score=3.0,
        ))
        db.add(CandidateVacancy(
            tenant_id=tenant.id, candidate_id=c2.id, vacancy_id=vacancy["id"],
            stage_id=active.id, status="new", manager_score=4.5,
        ))
        db.add(CandidateVacancy(
            tenant_id=tenant.id, candidate_id=c3.id, vacancy_id=vacancy["id"],
            stage_id=rejected.id, status="new", manager_score=5.0,
        ))
        await db.commit()

        items, _ = await service.list_vacancy_candidates_enriched(
            db, tenant.id, vacancy["id"]
        )
        names = [r["candidate_name"] for r in items]
        # C2 first (active, score 4.5), C1 next (active, 3.0), C3 last (terminal).
        assert names == ["C2", "C1", "C3"]


# ---------------------------------------------------------------------------
# PATCH candidate-vacancy with ETag
# ---------------------------------------------------------------------------


class TestPatchCandidateVacancy:
    async def test_if_match_match_bumps_version(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        added = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload()
        )
        cv_id = added["candidate_vacancy_id"]
        old_etag = added["etag"]

        result = await service.patch_candidate_vacancy(
            db,
            tenant.id,
            cv_id,
            CandidateVacancyPatch(manager_score=4.5),
            if_match=old_etag,
        )
        assert result["manager_score"] == 4.5
        assert result["version"] == 2
        assert result["etag"] == 'W/"2"'

        # Re-using the old etag now fails.
        with pytest.raises(HTTPException) as exc:
            await service.patch_candidate_vacancy(
                db,
                tenant.id,
                cv_id,
                CandidateVacancyPatch(manager_score=5.0),
                if_match=old_etag,
            )
        assert exc.value.status_code == 412

    async def test_stage_move_records_history_and_allows_terminal(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        added = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload()
        )

        stages = await service._get_applicable_stages(
            db, tenant.id, vacancy["id"]
        )
        hired = next(s for s in stages if s.code == "hired")

        result = await service.patch_candidate_vacancy(
            db,
            tenant.id,
            added["candidate_vacancy_id"],
            CandidateVacancyPatch(stage_id=hired.id, comment="Offer signed"),
        )
        assert result["stage"]["code"] == "hired"
        assert result["stage"]["stage_type"] == "terminal_positive"

        cv = (
            await db.execute(
                select(CandidateVacancy).where(
                    CandidateVacancy.id == added["candidate_vacancy_id"]
                )
            )
        ).scalar_one()
        history = cv.status_history or []
        assert len(history) == 1
        assert history[0]["comment"] == "Offer signed"


class TestDeleteCandidateVacancy:
    """HRP-181 REDO: detach a candidate from a vacancy funnel."""

    async def test_delete_removes_link_keeps_candidate(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        added = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload()
        )
        cv_id = added["candidate_vacancy_id"]
        candidate_id = added["id"]

        await service.delete_candidate_vacancy(db, tenant.id, cv_id)

        # Link is gone.
        link = (
            await db.execute(
                select(CandidateVacancy).where(CandidateVacancy.id == cv_id)
            )
        ).scalar_one_or_none()
        assert link is None

        # Canonical Candidate row stays so other vacancies can keep it.
        cand = (
            await db.execute(
                select(Candidate).where(Candidate.id == candidate_id)
            )
        ).scalar_one()
        assert cand.archived_at is None

    async def test_delete_unknown_returns_404(
        self, db: AsyncSession, tenant
    ):
        with pytest.raises(HTTPException) as exc:
            await service.delete_candidate_vacancy(
                db, tenant.id, uuid.uuid4()
            )
        assert exc.value.status_code == 404

    async def test_delete_cross_tenant_returns_404(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        added = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload()
        )
        cv_id = added["candidate_vacancy_id"]

        other_tenant = uuid.uuid4()
        with pytest.raises(HTTPException) as exc:
            await service.delete_candidate_vacancy(db, other_tenant, cv_id)
        assert exc.value.status_code == 404

        # And the link is still there.
        link = (
            await db.execute(
                select(CandidateVacancy).where(CandidateVacancy.id == cv_id)
            )
        ).scalar_one_or_none()
        assert link is not None


# ---------------------------------------------------------------------------
# Full card + inline edit + soft delete
# ---------------------------------------------------------------------------


class TestCandidateCard:
    async def test_full_card_includes_applications(
        self, db: AsyncSession, tenant, user
    ):
        vacancy1 = await _make_vacancy(db, tenant.id, user.id, "A")
        vacancy2 = await _make_vacancy(db, tenant.id, user.id, "B")

        first = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy1["id"],
            _manual_payload(full_name="Multi Apply", email="multi@example.com"),
        )
        # Link the same candidate to a second vacancy via the dup-prompt path.
        await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy2["id"],
            CandidateManualCreate(
                full_name="Multi Apply (linked)",
                email="another@example.com",
                link_candidate_id=first["id"],
            ),
        )

        card = await service.get_candidate_full_card(
            db, tenant.id, first["id"]
        )
        assert card["full_name"] == "Multi Apply"
        assert {a["vacancy_id"] for a in card["vacancy_applications"]} == {
            vacancy1["id"],
            vacancy2["id"],
        }
        assert card["candidate_files"] == []

    async def test_patch_candidate_inline_edit(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        added = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload(
                full_name="Old Name", email="old@example.com"
            )
        )

        card = await service.get_candidate_full_card(
            db, tenant.id, added["id"]
        )
        etag = card["etag"]

        updated = await service.patch_candidate(
            db,
            tenant.id,
            added["id"],
            CandidateCanonicalPatch(full_name="New Name", linkedin_url="https://li/x"),
            if_match=etag,
        )
        assert updated["full_name"] == "New Name"
        assert updated["linkedin_url"] == "https://li/x"
        # ETag stamp moves with updated_at.
        assert updated["etag"] != etag

    async def test_archive_then_recreate_same_email(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)
        added = await service.add_candidate_to_vacancy_manual(
            db, tenant.id, user.id, vacancy["id"], _manual_payload(
                full_name="Dee", email="dee@example.com"
            )
        )
        await service.archive_candidate(db, tenant.id, added["id"])

        # archived_at is set; the row is still reachable.
        c = await db.get(Candidate, added["id"])
        assert c.archived_at is not None

        # Re-create on the same email succeeds (partial index ignores archived).
        vacancy2 = await _make_vacancy(db, tenant.id, user.id, "V2")
        second = await service.add_candidate_to_vacancy_manual(
            db,
            tenant.id,
            user.id,
            vacancy2["id"],
            CandidateManualCreate(full_name="Dee v2", email="dee@example.com"),
        )
        assert second["id"] != added["id"]


# ---------------------------------------------------------------------------
# Stages: tenant defaults + per-vacancy override
# ---------------------------------------------------------------------------


class TestStagesEndpoints:
    async def test_tenant_defaults_returns_nine_stages(
        self, db: AsyncSession, tenant, user
    ):
        await service.seed_default_recruitment_stages(db, tenant.id)
        await db.commit()
        stages = await service.get_tenant_default_stages(db, tenant.id)
        codes = [s["code"] for s in stages]
        assert codes == [
            "new",
            "screening",
            "tech_interview",
            "manager_interview",
            "final_interview",
            "offer",
            "hired",
            "rejected",
            "withdrew",
        ]
        terminal_types = {s["stage_type"] for s in stages if s["code"] in (
            "hired", "rejected", "withdrew"
        )}
        assert terminal_types == {
            "terminal_positive", "terminal_negative", "terminal_neutral"
        }

    async def test_first_override_creates_vacancy_specific_rows(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)

        new_stages = await service.replace_vacancy_stages_override(
            db,
            tenant.id,
            vacancy["id"],
            VacancyStagesReplace(
                stages=[
                    VacancyStageReplaceItem(
                        name="Intro", code="intro", sort_order=10,
                        stage_type="active", color="blue",
                    ),
                    VacancyStageReplaceItem(
                        name="Done", code="done", sort_order=20,
                        stage_type="terminal_positive", color="emerald",
                    ),
                ]
            ),
        )
        assert [s["code"] for s in new_stages] == ["intro", "done"]

        effective = await service.get_effective_vacancy_stages(
            db, tenant.id, vacancy["id"]
        )
        assert [s["code"] for s in effective] == ["intro", "done"]
        assert all(s["vacancy_id"] == vacancy["id"] for s in effective)

    async def test_override_delete_with_candidates_returns_409(
        self, db: AsyncSession, tenant, user
    ):
        vacancy = await _make_vacancy(db, tenant.id, user.id)

        # First override: 2 stages.
        new_stages = await service.replace_vacancy_stages_override(
            db,
            tenant.id,
            vacancy["id"],
            VacancyStagesReplace(
                stages=[
                    VacancyStageReplaceItem(
                        name="Intro", code="intro", sort_order=10,
                        stage_type="active",
                    ),
                    VacancyStageReplaceItem(
                        name="Done", code="done", sort_order=20,
                        stage_type="terminal_positive",
                    ),
                ]
            ),
        )
        intro_id = next(s["id"] for s in new_stages if s["code"] == "intro")

        # Attach a candidate to ``intro``.
        cand = Candidate(
            tenant_id=tenant.id, full_name="Stuck", email="stuck@example.com"
        )
        db.add(cand)
        await db.flush()
        db.add(CandidateVacancy(
            tenant_id=tenant.id,
            candidate_id=cand.id,
            vacancy_id=vacancy["id"],
            stage_id=intro_id,
            status="new",
        ))
        await db.commit()

        # Attempt to drop ``intro`` → 409 with affected_candidate_count.
        # Sweep S8: the payload must satisfy the new funnel invariants
        # (at least one active stage) so the 422 validation fires later
        # than the candidate-conflict check — keep ``screen`` here so we
        # are checking the right rejection branch.
        with pytest.raises(HTTPException) as exc:
            await service.replace_vacancy_stages_override(
                db,
                tenant.id,
                vacancy["id"],
                VacancyStagesReplace(
                    stages=[
                        VacancyStageReplaceItem(
                            name="Screen", code="screen", sort_order=10,
                            stage_type="active",
                        ),
                        VacancyStageReplaceItem(
                            name="Done", code="done", sort_order=20,
                            stage_type="terminal_positive",
                        ),
                    ]
                ),
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "stage_has_candidates"
        assert exc.value.detail["affected_candidate_count"] == 1
