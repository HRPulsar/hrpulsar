"""Demo save-access: persist the visitor's keep-my-demo-data choice

The save-access modal gains a "keep the demo data" checkbox. The flag
rides the SignupRequest row through email verify → moderation; on
approve the demo tenant referenced by ``demo_tenant_id_snapshot`` is
converted into the real workspace instead of provisioning an empty one.

Server default false: pre-migration rows (and the landing form, which
has no demo session) keep today's fresh-tenant behaviour.

Revision ID: demokeepdata01
Revises: hrp581recidx
Create Date: 2026-08-18 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "demokeepdata01"
down_revision: str | None = "hrp581recidx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signup_requests",
        sa.Column(
            "keep_demo_data",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("signup_requests", "keep_demo_data")
