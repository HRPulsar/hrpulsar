"""HRP-575: persist the applicant's locale on signup_requests

HRP-513 routed the visitor's chosen interface locale into the signed-out
email funnels, but only for emails sent inside the same request. The
moderation decision arrives minutes or days later, from Slack or the
platform-admin UI — neither of which carries the applicant's headers —
so approve/reject emails fell back to the deployment default.

The column stores the locale resolved at submit time so the decision
email can be rendered in the language the applicant actually used.

Nullable, no backfill: ``resolve_locale`` checks ``user_language`` ahead
of the tenant/deployment default, so backfilling pre-migration rows with
a literal ``'en'`` would outrank the correct default on non-English
installations and flip their in-flight moderation emails to English.
``NULL`` means "not captured" and falls through the resolution chain
exactly like the pre-HRP-575 code did.

Revision ID: hrp575signuploc
Revises: hrp570salcur
Create Date: 2026-08-14 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp575signuploc"
down_revision: str | None = "hrp570salcur"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signup_requests",
        sa.Column(
            "locale",
            sa.String(length=10),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("signup_requests", "locale")
