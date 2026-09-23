"""HRP-866: the agent setup bundle of a container - which steps make the
guide and in what order, a README that needs no model, and a zip of the
ready skill files that whoever reads the container may download. A
download is a read: nothing is generated, nothing is queued."""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.core.i18n import translate
from app.modules.primitives import catalog_data
from app.modules.work import bundle, coverage, service
from app.modules.work.models import WorkStepSkill
from app.modules.work.router import router
from app.modules.work.schemas import StepUpdate
from sqlalchemy import func, select

from tests.unit.test_coverage_matching import _container, _employee, _step
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded
from tests.unit.test_work_access import _person

no_mapping_enqueue = _quiet
seeded = _seeded

BACKEND = Path(__file__).resolve().parents[2]


def _row(position, pack, mode="automatable", *, hours=None, verdict="agent", name=None):
    # ``review_human_share`` the way ``coverage.review_share`` sets it: the
    # default share inside the review bucket, nothing outside it.
    share = (
        coverage.DEFAULT_REVIEW_HUMAN_SHARE
        if mode is not None and coverage.BUCKET_OF_MODE[mode] == "to_review"
        else None
    )
    return {
        "step_id": uuid.uuid4(),
        "position": position,
        "title": f"Step {position}",
        "verdict": verdict,
        "mode": mode,
        "hours_per_year": hours,
        "review_human_share": share,
        "agent": pack
        and {"pack_id": None, "pack_code": pack, "agent_id": None, "agent_name": name},
    }


class TestGroups:
    def test_groups_by_agent_type_largest_hours_first(self):
        rows = [
            _row(1, "extraction", hours=100),
            _row(2, "drafting", "draft_then_review", hours=300),
            _row(3, "extraction", "review_required", hours=50, name="Claude Code"),
            _row(4, "coordinator"),
        ]
        groups = bundle.agent_groups(rows)
        assert [g["pack_code"] for g in groups] == [
            "drafting",
            "extraction",
            "coordinator",
        ]
        extraction = groups[1]
        assert [r["position"] for r in extraction["steps"]] == [1, 3]
        # 100 of the first step and half of the 50 that go to review -
        # the other half stays with the checker (HRP-861).
        assert extraction["hours"] == 125
        assert extraction["agent_names"] == {"Claude Code"}
        # No estimate is no hours, not a missing group.
        assert groups[2]["hours"] == 0

    def test_a_tie_in_hours_goes_by_the_first_step(self):
        rows = [_row(5, "drafting", hours=10), _row(2, "extraction", hours=10)]
        assert [g["pack_code"] for g in bundle.agent_groups(rows)] == [
            "extraction",
            "drafting",
        ]

    def test_hours_leave_out_what_the_checker_keeps(self):
        """HRP-858: the guide and the summary count the same hours - what a
        reviewed step frees is its hours less its checker's share, so the
        section never promises more than the process card does."""
        row = _row(1, "drafting", "review_required", hours=100)
        row["review_human_share"] = 30
        assert bundle.agent_groups([row])[0]["hours"] == 70

    def test_leaves_out_what_no_agent_takes(self):
        rows = [
            # A person the company named outranks the agent that could.
            _row(1, "extraction", verdict="human", hours=500),
            # Stays with people: outside the two agent buckets.
            _row(2, "extraction", "blocked_judgment", hours=500),
            _row(3, None, verdict="gap", hours=500),
            _row(4, None, None, verdict="out_of_scope"),
        ]
        assert bundle.agent_groups(rows) == []


class TestPaths:
    def test_folder_is_the_skill_name_and_a_shared_name_takes_the_position(self):
        rows = [_row(1, "extraction"), _row(2, "extraction"), _row(3, "extraction")]
        groups = bundle.agent_groups(rows)
        names = {
            rows[0]["step_id"]: "bank-reconciliation",
            rows[1]["step_id"]: "bank-reconciliation",
        }
        paths = bundle.skill_paths(groups, names)
        assert paths == {
            rows[0]["step_id"]: "skills/bank-reconciliation/SKILL.md",
            rows[1]["step_id"]: "skills/bank-reconciliation-2/SKILL.md",
        }

    def test_a_name_that_already_ends_in_a_position_keeps_its_own_folder(self):
        # The suffix is a step position, so a stored name may already look
        # like a deduplicated one. One pass would hand both the same folder
        # and the zip, keyed by path, would drop a file the README lists.
        rows = [_row(1, "extraction"), _row(2, "extraction"), _row(3, "extraction")]
        groups = bundle.agent_groups(rows)
        paths = bundle.skill_paths(
            groups,
            {
                rows[0]["step_id"]: "close-the-books-3",
                rows[1]["step_id"]: "close-the-books",
                rows[2]["step_id"]: "close-the-books",
            },
        )
        assert paths == {
            rows[0]["step_id"]: "skills/close-the-books-3/SKILL.md",
            rows[1]["step_id"]: "skills/close-the-books/SKILL.md",
            rows[2]["step_id"]: "skills/close-the-books-4/SKILL.md",
        }

    def test_a_stored_name_cannot_leave_the_skills_folder(self):
        rows = [_row(1, "extraction"), _row(2, "extraction")]
        groups = bundle.agent_groups(rows)
        paths = bundle.skill_paths(
            groups, {rows[0]["step_id"]: "../../etc/passwd", rows[1]["step_id"]: None}
        )
        assert paths[rows[0]["step_id"]] == "skills/etc-passwd/SKILL.md"
        assert paths[rows[1]["step_id"]] == "skills/step-2/SKILL.md"


class TestReadme:
    def _render(self, locale, *, review=True, missing=True):
        rows = [
            _row(1, "extraction", hours=120.4, name="Claude Code"),
            _row(2, "drafting", "draft_then_review" if review else "automatable"),
        ]
        groups = bundle.agent_groups(rows)
        names = {rows[0]["step_id"]: "pull-the-numbers"}
        if not missing:
            names[rows[1]["step_id"]] = "draft-the-note"
        paths = bundle.skill_paths(groups, names)
        titles = {"extraction": "Extraction", "drafting": "Drafting"}
        return bundle.build_readme("Month-end close", groups, paths, titles, locale)

    def test_names_the_agents_the_steps_and_the_files(self):
        text = self._render("en")
        assert text.startswith("# Agent setup guide: Month-end close\n")
        assert "Agent types this work needs: 2." in text
        assert "## 1. Extraction (`extraction`)" in text
        assert "## 2. Drafting (`drafting`)" in text
        assert "- Agent: Claude Code (registered)" in text
        assert "- Agent: not registered yet" in text
        assert "- Hours a year: about 120" in text
        assert "- Hours a year: not estimated yet" in text
        assert (
            "  - 1. Step 1 (moves to an agent) - `skills/pull-the-numbers/SKILL.md`"
            in text
        )
        assert "  - 2. Step 2 (moves to review) - no skill file yet" in text

    def test_every_key_resolves_in_every_core_catalog(self):
        # Two of the keys are computed, so the literal-key guard of
        # test_i18n_coverage cannot see them: a key that is missing comes
        # back verbatim, and that is what this looks for.
        rendered = {}
        for locale in ("en", "de"):
            text = self._render(locale)
            assert "work_bundle." not in text, locale
            assert not re.search(r"\{[a-z_]+\}", text), locale
            rendered[locale] = text
        assert rendered["de"] != rendered["en"]
        assert translate("work_bundle.todo_heading", "de") in rendered["de"]

    def test_the_todo_list_asks_only_for_what_applies(self):
        full = self._render("en")
        assert "5. For the steps without a skill file" in full
        assert "4. On every step that moves to review" in full

        done = self._render("en", review=False, missing=False)
        assert "moves to review" not in done
        assert "without a skill file" not in done
        assert "3. Register the agent" in done and "\n4. " not in done

        # The numbering closes up when only one of the two applies.
        assert "4. For the steps without a skill file" in self._render(
            "en", review=False
        )


async def _ready_skill(db, tenant, step, name, content, *, status="ready"):
    row = WorkStepSkill(
        tenant_id=tenant.id,
        step_id=step["id"],
        catalog_version=service.CATALOG_VERSION,
        status=status,
        skill_name=name,
        content=content,
    )
    db.add(row)
    await db.commit()
    return row


class TestRoute:
    async def test_zip_of_the_ready_skills_and_a_readme(
        self, db, tenant, user, seeded, auth_client
    ):
        c = await _container(db, tenant, user, title="Bank postings")
        url = f"/api/work/containers/{c.id}/agent-bundle"
        pull = await _step(
            db, tenant, c, ["P1"], title="Pull", hours_per_run=2, runs_per_year=50
        )
        check = await _step(
            db,
            tenant,
            c,
            ["P1", "P2"],
            title="Check",
            hours_per_run=4,
            runs_per_year=100,
        )
        await _step(db, tenant, c, ["P6"], title="Decide")
        taken = await _step(db, tenant, c, ["P1"], title="Taken by a person")

        # Steps an agent takes, none with a file yet: nothing to download.
        assert (await auth_client.get(url)).status_code == 404

        await _ready_skill(db, tenant, pull, "pull-the-lines", "---\nname: pull\n---\n")
        # A failed regeneration keeps the last working file in the row. The
        # screen counts the step as not ready, so the archive leaves it out.
        stale = await _step(db, tenant, c, ["P1"], title="Stale")
        await _ready_skill(db, tenant, stale, "stale", "old", status="failed")
        # A file on a step the company gave to a person is not the guide's.
        await _ready_skill(db, tenant, taken, "taken", "---\nname: taken\n---\n")
        employee = await _employee(db, tenant)
        await service.update_step(
            db, tenant.id, taken["id"], StepUpdate(executor_employee_id=employee.id)
        )

        rows_before = await db.scalar(select(func.count()).select_from(WorkStepSkill))
        with (
            patch("app.core.task_enqueue.enqueue_task") as enqueue,
            patch.object(coverage, "compute", wraps=coverage.compute) as compute,
        ):
            res = await auth_client.get(url)
        assert res.status_code == 200, res.text
        # The reader of a download must not start a competence mapping run.
        assert compute.call_args.kwargs["schedule_mapping"] is False
        assert res.headers["content-type"] == "application/zip"
        assert (
            res.headers["content-disposition"]
            == 'attachment; filename="agent-skills.zip"'
        )
        # A read: no generation queued, no skill row written.
        assert enqueue.call_count == 0
        assert (
            await db.scalar(select(func.count()).select_from(WorkStepSkill))
            == rows_before
        )

        archive = zipfile.ZipFile(io.BytesIO(res.content))
        assert sorted(archive.namelist()) == [
            "README.md",
            "skills/pull-the-lines/SKILL.md",
        ]
        assert (
            archive.read("skills/pull-the-lines/SKILL.md").decode()
            == "---\nname: pull\n---\n"
        )
        readme = archive.read("README.md").decode()
        assert readme.startswith("# Agent setup guide: Bank postings\n")
        # 400 h a year before 100 h a year; the blocked and the assigned
        # steps are in neither group.
        assert readme.index("Compliance check") < readme.index("Extraction")
        assert f"{check['position']}. Check" in readme
        assert "`skills/pull-the-lines/SKILL.md`" in readme
        assert "Decide" not in readme and "Taken by a person" not in readme
        assert (
            f"{stale['position']}. Stale (moves to an agent) - no skill file yet"
            in readme
        )

    async def test_readme_follows_the_content_language(
        self, db, tenant, user, seeded, auth_client
    ):
        from app.modules.ai_settings import service as ai_settings_service
        from app.modules.ai_settings.schemas import AISettingsUpdate

        await ai_settings_service.update(
            db, tenant.id, AISettingsUpdate(content_language="de")
        )
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P1"])
        await _ready_skill(db, tenant, step, "pull", "x")

        res = await auth_client.get(f"/api/work/containers/{c.id}/agent-bundle")
        readme = zipfile.ZipFile(io.BytesIO(res.content)).read("README.md").decode()
        assert translate("work_bundle.todo_heading", "de") in readme

    async def test_a_hidden_container_is_a_404(self, client, auth_client, db, tenant):
        await db.execute(catalog_data.seed_insert())
        await db.commit()
        created = await auth_client.post(
            "/api/work/containers", json={"type": "process", "title": "Payroll run"}
        )
        cid = created.json()["id"]
        _, _, stranger = await _person(db, tenant, "employee")
        res = await client.get(
            f"/api/work/containers/{cid}/agent-bundle", headers=stranger
        )
        assert res.status_code == 404


def test_the_frontend_calls_the_url_and_saves_the_name_the_backend_declares():
    route = next(r for r in router.routes if r.name == "download_agent_bundle")
    assert route.methods == {"GET"}
    called = route.path.replace("{container_id}", "${containerId}")
    source = (BACKEND.parent / "frontend/src/lib/api/work.ts").read_text(
        encoding="utf-8"
    )
    assert f"api.fetchBlob(`{called}`)" in source
    # The browser saves a blob under the name the screen sets, never the
    # one the header carries: the two names have to be written alike.
    guide = (
        BACKEND.parent / "frontend/src/components/coverage/agent-guide.tsx"
    ).read_text(encoding="utf-8")
    assert f'BUNDLE_FILE_NAME = "{bundle.ARCHIVE_NAME}"' in guide
