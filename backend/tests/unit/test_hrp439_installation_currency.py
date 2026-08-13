"""HRP-439: HR money defaults follow the installation, not a literal.

Salary ranges on the grade chain defaulted to RUB and compensations to
USD, so on any given site at least one of them was wrong: the flagship
quotes USD, the German white-label EUR, the Russian one RUB. Both now
read ``BILLING_CURRENCY`` — the per-installation knob that already drives
the billing money layer.

``settings`` is a singleton, so the defaults have to resolve per
instantiation (``default_factory`` / a callable column default). These
tests monkeypatch the setting and would fail on any import-time capture.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.core.currency import FALLBACK_CURRENCY, installation_currency
from app.modules.employee.schemas import CompensationCreate
from app.modules.grade_system.schemas import GradeSpecializationCreate
from app.modules.specialization.schemas import SpecializationGradeAttrs


class TestInstallationCurrency:
    def test_defaults_to_usd_in_community(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.billing_currency", "USD")
        assert installation_currency() == "USD"

    def test_follows_the_configured_currency(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.billing_currency", "EUR")
        assert installation_currency() == "EUR"

    def test_normalises_case_and_padding(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.billing_currency", " rub ")
        assert installation_currency() == "RUB"

    @pytest.mark.parametrize("bad", ["", "E", "EURO", "12", "€€€", None])
    def test_malformed_value_falls_back(self, monkeypatch, bad):
        # The column is NOT NULL and the schemas demand exactly three
        # characters — a misconfigured env must not produce rows that fail
        # validation on read-back.
        monkeypatch.setattr("app.config.settings.billing_currency", bad)
        assert installation_currency() == FALLBACK_CURRENCY


class TestSchemaDefaults:
    @pytest.mark.parametrize("currency", ["USD", "EUR", "RUB"])
    def test_grade_chain_and_compensation_agree_on_the_site_currency(
        self, monkeypatch, currency
    ):
        monkeypatch.setattr("app.config.settings.billing_currency", currency)

        chain = GradeSpecializationCreate(
            grade_id="00000000-0000-0000-0000-000000000001",
            specialization_id="00000000-0000-0000-0000-000000000002",
        )
        attrs = SpecializationGradeAttrs()
        comp = CompensationCreate(
            type="salary", amount=1000, effective_date=date(2026, 1, 1)
        )

        assert chain.salary_currency == currency
        assert attrs.salary_currency == currency
        # Compensations used to hardcode USD while the grade chain
        # hardcoded RUB — the same tenant could not agree with itself.
        assert comp.currency == currency

    def test_explicit_currency_still_wins(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.billing_currency", "EUR")
        chain = GradeSpecializationCreate(
            grade_id="00000000-0000-0000-0000-000000000001",
            specialization_id="00000000-0000-0000-0000-000000000002",
            salary_currency="GBP",
        )
        assert chain.salary_currency == "GBP"


class TestOrmDefault:
    async def test_created_chain_stores_the_installation_currency(
        self, db, tenant, monkeypatch
    ):
        """End to end through the service: no currency in, site currency out."""
        from app.modules.dictionary import service as dict_service
        from app.modules.dictionary.schemas import DictionaryItemCreate
        from app.modules.grade_system import service as grade_service

        monkeypatch.setattr("app.config.settings.billing_currency", "EUR")

        spec = await dict_service.create_item(
            db, tenant.id, "specialization", DictionaryItemCreate(title="Cur Spec")
        )
        grade = await dict_service.create_item(
            db, tenant.id, "grade", DictionaryItemCreate(title="Cur Grade")
        )
        chain = await grade_service.create_chain(
            db,
            tenant.id,
            GradeSpecializationCreate(
                grade_id=grade["id"], specialization_id=spec["id"]
            ),
        )
        assert chain["salary_currency"] == "EUR"
