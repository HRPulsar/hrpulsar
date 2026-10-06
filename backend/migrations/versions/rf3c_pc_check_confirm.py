"""Confirm each saved public check by its own letter, HRP-926 review

Revision ID: rf3c_pc_check_confirm
Revises: hrp931pcfunnel
Create Date: 2026-10-05 10:00:00.000000

A save proves nothing about owning an address, so a check is kept only by
the click of its own confirmation letter - also on an address confirmed
before - and the save's marketing opt-in waits on that click:

* ``public_checks.confirm_token_hash`` / ``confirm_expires_at`` /
  ``confirm_marketing`` - the token of the check's letter and the opt-in
  of its save.
* ``public_check_emails.confirm_token_hash`` / ``confirm_expires_at``
  dropped: one token per address let any save burn the letter of another.
  Letters sent before this revision stop working; the visitor saves again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "rf3c_pc_check_confirm"
down_revision: str | Sequence[str] | None = "hrp931pcfunnel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "public_checks",
        sa.Column("confirm_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "public_checks",
        sa.Column("confirm_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "public_checks",
        sa.Column(
            "confirm_marketing",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "public_checks_confirm_token_hash_key", "public_checks", ["confirm_token_hash"]
    )
    op.drop_constraint(
        "public_check_emails_confirm_token_hash_key",
        "public_check_emails",
        type_="unique",
    )
    op.drop_column("public_check_emails", "confirm_expires_at")
    op.drop_column("public_check_emails", "confirm_token_hash")


def downgrade() -> None:
    op.add_column(
        "public_check_emails",
        sa.Column("confirm_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "public_check_emails",
        sa.Column("confirm_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "public_check_emails_confirm_token_hash_key",
        "public_check_emails",
        ["confirm_token_hash"],
    )
    op.drop_constraint(
        "public_checks_confirm_token_hash_key", "public_checks", type_="unique"
    )
    op.drop_column("public_checks", "confirm_marketing")
    op.drop_column("public_checks", "confirm_expires_at")
    op.drop_column("public_checks", "confirm_token_hash")
