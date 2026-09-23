"""HRP-871: what a human match stands on - the competences behind the step's
capabilities, each with the score it was read off and the passing score it
was held against. The grounds ride on the matched person, so the one place
that hides a person from a reader hides the scores with them."""

from __future__ import annotations

from app.modules.primitives import catalog_data
from app.modules.work import coverage

from tests.unit.test_coverage_matching import (
    _competence,
    _container,
    _done,
    _employee,
    _position_expecting,
    _row,
    _step,
)
from tests.unit.test_coverage_matching import no_mapping_enqueue as _quiet
from tests.unit.test_coverage_matching import seeded as _seeded
from tests.unit.test_work_access import _person

# Re-exported under the names the tests below ask for: pytest resolves a
# fixture by the name it is bound to in this module.
no_mapping_enqueue = _quiet
seeded = _seeded


class TestGrounds:
    async def test_an_assessed_match_names_the_competence_and_the_score(
        self, db, tenant, user, seeded
    ):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6", "P7"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, comp, 82)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "assessed"
        # No grade specialization behind the person: the default bar.
        assert row["human"]["passing_score"] == coverage.DEFAULT_PASSING_SCORE
        assert row["human"]["grounds"] == [
            {
                "competence_id": comp.id,
                "title": comp.title,
                "state": "assessed",
                "percent": 82,
                # Only what this step asks for, not all the competence maps to.
                "codes": ["P6"],
            }
        ]

    async def test_an_expected_match_has_no_score(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        position = await _position_expecting(db, tenant, comp, passing_score=60)
        await _employee(db, tenant, position=position)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "expected"
        assert row["human"]["passing_score"] == 60
        assert [(g["state"], g["percent"]) for g in row["human"]["grounds"]] == [
            ("expected", None)
        ]

    async def test_the_bar_is_the_grade_specializations(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        position = await _position_expecting(db, tenant, comp, passing_score=60)
        emp = await _employee(db, tenant, position=position)
        await _done(db, tenant, emp, comp, 65)  # under 75, over this grade's 60
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "assessed"
        assert row["human"]["passing_score"] == 60
        assert row["human"]["grounds"][0]["percent"] == 65

    async def test_a_mixed_match_lists_confirmed_first(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6", "P7"])
        expected = await _competence(db, tenant.id, ["P7"])
        proven = await _competence(db, tenant.id, ["P6"])
        other = await _competence(db, tenant.id, ["P8"])  # not this step's
        position = await _position_expecting(db, tenant, expected)
        emp = await _employee(db, tenant, position=position)
        await _done(db, tenant, emp, proven, 90)
        await _done(db, tenant, emp, other, 95)
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "expected"
        assert [
            (g["competence_id"], g["state"], g["codes"])
            for g in row["human"]["grounds"]
        ] == [
            (proven.id, "assessed", ["P6"]),
            (expected.id, "expected", ["P7"]),
        ]

    async def test_a_failed_competence_is_no_ground(self, db, tenant, user, seeded):
        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        failed = await _competence(db, tenant.id, ["P6"])
        passed = await _competence(db, tenant.id, ["P6"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, failed, 40)
        await _done(db, tenant, emp, passed, 80)
        row, _ = await _row(db, tenant, c, step["id"])
        assert [g["competence_id"] for g in row["human"]["grounds"]] == [passed.id]

    async def test_an_assigned_executor_has_none(self, db, tenant, user, seeded):
        """The company named them; nothing was matched, nothing to explain."""
        from app.modules.work import service
        from app.modules.work.schemas import CoverageHuman, StepUpdate

        c = await _container(db, tenant, user)
        step = await _step(db, tenant, c, ["P6"])
        comp = await _competence(db, tenant.id, ["P6"])
        emp = await _employee(db, tenant)
        await _done(db, tenant, emp, comp, 90)
        await service.update_step(
            db, tenant.id, step["id"], StepUpdate(executor_employee_id=emp.id)
        )
        row, _ = await _row(db, tenant, c, step["id"])
        assert row["human"]["label"] == "assigned"
        assert "grounds" not in row["human"]
        assert CoverageHuman.model_validate(row["human"]).grounds == []


class TestWhoSeesTheGrounds:
    async def test_the_scores_travel_only_with_a_visible_person(
        self, client, auth_client, db, tenant
    ):
        """HRP-810's rule, unchanged: admin sees everyone, a person sees
        themselves, a colleague with no HR scope sees neither the person nor
        one byte of what the match stood on."""
        await db.execute(catalog_data.seed_insert())
        await db.commit()
        cid = (
            await auth_client.post(
                "/api/work/containers", json={"type": "process", "title": "Bonus pool"}
            )
        ).json()["id"]
        sid = (
            await auth_client.post(
                f"/api/work/containers/{cid}/steps",
                json={"title": "Decide the split", "primitive_codes": ["P6"]},
            )
        ).json()["id"]
        opened = await auth_client.put(
            f"/api/work/containers/{cid}/access",
            json={"visibility": "company", "rules": []},
        )
        assert opened.status_code == 200, opened.text
        _, matched, matched_h = await _person(db, tenant, "employee")
        _, _, colleague_h = await _person(db, tenant, "employee")
        comp = await _competence(db, tenant.id, ["P6"])
        await _done(db, tenant, matched, comp, 88)
        url = f"/api/work/containers/{cid}/coverage"

        def human_of(response):
            assert response.status_code == 200, response.text
            return next(r for r in response.json()["steps"] if r["step_id"] == sid)[
                "human"
            ]

        for seen in (
            await auth_client.get(url),
            await client.get(url, headers=matched_h),
        ):
            human = human_of(seen)
            assert human["employee_id"] == str(matched.id)
            assert human["passing_score"] == 75
            assert [(g["title"], g["percent"]) for g in human["grounds"]] == [
                (comp.title, 88)
            ]

        hidden = await client.get(url, headers=colleague_h)
        assert human_of(hidden) is None
        assert comp.title not in hidden.text
        assert str(comp.id) not in hidden.text
        assert str(matched.id) not in hidden.text
        assert "grounds" not in hidden.text
