"""
Seed demo data for HRPulsar (self-hosted / community edition).

Creates a realistic demo company "Pulsar Technologies" with:
- Admin user + 50 employees across 5 divisions (3 levels deep)
- Dictionary items (grades, specializations, competence types)
- Competence groups, competences, and indicators
- 3 assessments (self, 180, 360) in various statuses with answers
- PDPs with items, materials, progress
- Mass exam with questions
- Talent market cards (vacancy, talent, project)

Usage:
    python scripts/seed_demo.py           # seed demo data
    python scripts/seed_demo.py --reset   # drop existing demo tenant and re-seed

To reset everything from scratch:
    docker compose down -v                # stop containers, delete volumes
    docker compose up -d db redis         # start fresh DB + Redis
    make migrate                          # run migrations
    make seed-demo                        # seed demo data
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import select, text

sys.path.insert(0, "backend")

from app.core.security import hash_password  # noqa: E402
from app.core.seed import (  # noqa: E402
    DEMO_PASSWORD,
    fetch_ref_data,
    populate_tenant,
    uid,
)
from app.database import async_session  # noqa: E402
from app.modules.auth.models import User, user_roles  # noqa: E402
from app.modules.company.models import Tenant  # noqa: E402
from app.modules.storage.models import (
    File,  # noqa: E402, F401 — register FK target for Tenant.logo_file_id
)

DEMO_SLUG = "pulsar-technologies"
DEMO_ADMIN_EMAIL = "admin@pulsar.demo"


async def seed(reset: bool = False):
    async with async_session() as db:
        # Check / reset existing tenant
        existing = (
            await db.execute(select(Tenant).where(Tenant.slug == DEMO_SLUG))
        ).scalar_one_or_none()

        if existing and not reset:
            print(
                f"Demo tenant '{DEMO_SLUG}' already exists (id={existing.id}). Skipping."
            )
            print("Use --reset to drop and re-seed:")
            print("  python scripts/seed_demo.py --reset")
            return

        if existing and reset:
            print(f"Resetting demo tenant '{DEMO_SLUG}'...")
            tid = str(existing.id)
            # Find all tables with tenant_id column and delete tenant data
            # Using replica mode to skip FK trigger checks
            await db.execute(text("SET session_replication_role = 'replica'"))
            result = await db.execute(text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE column_name = 'tenant_id' AND table_schema = 'public'"
            ))
            tables = [row[0] for row in result.fetchall()]
            for tbl in tables:
                await db.execute(text(f'DELETE FROM "{tbl}" WHERE tenant_id = :tid'), {"tid": tid})
            await db.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await db.execute(text("SET session_replication_role = 'origin'"))
            await db.flush()
            print("  Deleted existing tenant (cascade).")

        # Create tenant
        print("Creating tenant...")
        tenant = Tenant(
            id=uid(), name="Pulsar Technologies", slug=DEMO_SLUG, is_active=True
        )
        db.add(tenant)
        await db.flush()

        # Create admin user
        print("Creating admin user...")
        admin_user = User(
            id=uid(),
            tenant_id=tenant.id,
            email=DEMO_ADMIN_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            first_name="Demo",
            last_name="Admin",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(admin_user)
        await db.flush()

        # Assign admin role
        ref_data = await fetch_ref_data(db)
        await db.execute(
            user_roles.insert().values(
                user_id=admin_user.id, role_id=ref_data["role_map"]["admin"].id
            )
        )

        # Populate tenant with full demo data
        print("Populating tenant data...")
        result = await populate_tenant(
            db,
            tenant_id=tenant.id,
            admin_user=admin_user,
            ref_data=ref_data,
        )

        await db.commit()

        employees = result["employees"]
        div = result["divisions"]
        competences = result["competences"]
        positions = result["positions"]

        print()
        print("=" * 60)
        print("  Demo data seeded successfully!")
        print("=" * 60)
        print()
        print("  Company:     Pulsar Technologies")
        print(f"  Admin:       {DEMO_ADMIN_EMAIL}")
        print(f"  Password:    {DEMO_PASSWORD}")
        print(f"  Employees:   {len(employees)} + 1 admin = {len(employees) + 1}")
        print(f"  Divisions:   {len(div)}")
        print(f"  Positions:   {len(positions)}")
        print(f"  Competences: {len(competences)}")
        print("  Assessments: 3 (self/done, 180/in_progress, 360/draft)")
        print("  PDPs:        3 (active, draft, completed)")
        print("  Exam:        1 mass exam, 10 assigned")
        print("  Talent cards: 3 (vacancy, talent, project)")
        print()
        print("  To reset from scratch:")
        print("    docker compose down -v && docker compose up -d db redis")
        print("    make migrate && make seed-demo")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo data for HRPulsar")
    parser.add_argument(
        "--reset", action="store_true", help="Drop existing demo tenant and re-seed"
    )
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))
