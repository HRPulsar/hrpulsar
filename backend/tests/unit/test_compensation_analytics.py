"""Tests for GF5: Compensation summary analytics."""

from datetime import date

from app.modules.analytics import service as analytics_service
from app.modules.company.models import Division
from app.modules.employee.models import Compensation
from sqlalchemy.ext.asyncio import AsyncSession


class TestCompensationAnalytics:
    async def test_empty_compensation_stats(self, db: AsyncSession, tenant):
        result = await analytics_service.compensation_stats(db, tenant.id)
        assert result["total_records"] == 0
        assert result["total_amount"] == 0
        assert result["by_type"] == {}
        assert result["by_division"] == []

    async def test_stats_by_type(self, db: AsyncSession, tenant, employee):
        # Add salary and bonus
        db.add(
            Compensation(
                employee_id=employee.id,
                tenant_id=tenant.id,
                type="salary",
                amount=500000,
                currency="USD",
                effective_date=date(2024, 1, 1),
            )
        )
        db.add(
            Compensation(
                employee_id=employee.id,
                tenant_id=tenant.id,
                type="bonus",
                amount=100000,
                currency="USD",
                effective_date=date(2024, 6, 1),
            )
        )
        await db.commit()

        result = await analytics_service.compensation_stats(db, tenant.id)
        assert result["total_records"] == 2
        assert "salary" in result["by_type"]
        assert result["by_type"]["salary"]["count"] == 1
        assert result["by_type"]["salary"]["total"] == 500000
        assert "bonus" in result["by_type"]

    async def test_stats_by_division(self, db: AsyncSession, tenant, employee):
        # Create division and assign employee
        div = Division(tenant_id=tenant.id, name="Engineering")
        db.add(div)
        await db.flush()
        employee.division_id = div.id

        db.add(
            Compensation(
                employee_id=employee.id,
                tenant_id=tenant.id,
                type="salary",
                amount=600000,
                currency="USD",
                effective_date=date(2024, 1, 1),
            )
        )
        await db.commit()

        result = await analytics_service.compensation_stats(db, tenant.id)
        assert len(result["by_division"]) == 1
        assert result["by_division"][0]["division_name"] == "Engineering"
        assert result["by_division"][0]["avg_salary"] == 600000.0

    async def test_ended_compensation_excluded(
        self, db: AsyncSession, tenant, employee
    ):
        """Ended compensation records should not appear in active stats."""
        db.add(
            Compensation(
                employee_id=employee.id,
                tenant_id=tenant.id,
                type="salary",
                amount=400000,
                currency="USD",
                effective_date=date(2023, 1, 1),
                end_date=date(2023, 12, 31),
            )
        )
        db.add(
            Compensation(
                employee_id=employee.id,
                tenant_id=tenant.id,
                type="salary",
                amount=500000,
                currency="USD",
                effective_date=date(2024, 1, 1),
            )
        )
        await db.commit()

        result = await analytics_service.compensation_stats(db, tenant.id)
        assert result["total_records"] == 1
        assert result["by_type"]["salary"]["total"] == 500000
