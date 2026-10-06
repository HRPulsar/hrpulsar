"""Save public check results by email, HRP-926

Revision ID: hrp926pcsave
Revises: hrp911packid
Create Date: 2026-10-03 10:00:00.000000

* ``public_check_emails`` - an address a visitor saved checks with: its
  consent, marketing opt-in, confirmation, unsubscribe and the sha256 of
  its link tokens (see ``PublicCheckEmail``).
* ``public_checks.email_id`` - the address a check is saved with, deleted
  with it.
* ``public_checks.owner_key_hash`` - sha256 of the owner key handed once to
  the browser that ran the check: a shared result link reads, only the
  owner key saves.
* ``public_checks.moved_at`` / ``moved_tenant_id`` - reserved for HRP-927,
  which moves saved checks into a new workspace; nothing writes them yet.
* Indexes on ``public_checks.container_id`` (the purge's anti-join over
  sandbox containers, review of HRP-923) and ``email_id``.
* Email templates ``public_check_confirm`` and ``public_check_magic_link``,
  en and de. Russian is an enterprise-only locale and the check's letters
  go out in en or de only, so there is no ru row.

Additive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "hrp926pcsave"
down_revision: str | Sequence[str] | None = "hrp911packid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FOOTER = {
    "en": (
        '<p style="font-size: 12px; color: #6b7280;">You received this email '
        "because this address was used to save a process check on "
        '{{ check_host }}. <a href="{{ unsubscribe_url }}">Unsubscribe from '
        "product news</a></p>"
    ),
    "de": (
        '<p style="font-size: 12px; color: #6b7280;">Sie erhalten diese '
        "E-Mail, weil mit dieser Adresse eine Prozessprüfung auf "
        '{{ check_host }} gespeichert wurde. <a href="{{ unsubscribe_url }}">'
        "Produktneuigkeiten abbestellen</a></p>"
    ),
}

# (code, locale, subject, body)
_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    (
        "public_check_confirm",
        "en",
        "Confirm your email to keep your process check",
        "<p>Confirm this address and we will keep the results of your process "
        "check with no expiry date. All checks you save with this address "
        "open from one link.</p>"
        '<p><a href="{{ link_url }}">Confirm my email</a></p>'
        "<p>The link works for 7 days. If you did not save a check, ignore "
        "this email: an unconfirmed result is deleted after 10 days.</p>"
        + _FOOTER["en"],
    ),
    (
        "public_check_confirm",
        "de",
        "Bestätigen Sie Ihre E-Mail-Adresse, um Ihre Prozessprüfung zu behalten",
        "<p>Bestätigen Sie diese Adresse, und wir bewahren die Ergebnisse "
        "Ihrer Prozessprüfung ohne Ablaufdatum auf. Alle Prüfungen, die Sie "
        "mit dieser Adresse speichern, öffnen Sie über einen Link.</p>"
        '<p><a href="{{ link_url }}">E-Mail-Adresse bestätigen</a></p>'
        "<p>Der Link ist 7 Tage gültig. Wenn Sie keine Prüfung gespeichert "
        "haben, ignorieren Sie diese E-Mail: Ein unbestätigtes Ergebnis wird "
        "nach 10 Tagen gelöscht.</p>" + _FOOTER["de"],
    ),
    (
        "public_check_magic_link",
        "en",
        "Your saved process checks",
        "<p>Here is your link to all process checks saved with this "
        "address.</p>"
        '<p><a href="{{ link_url }}">Open my checks</a></p>'
        "<p>The link works for 24 hours. If you did not ask for it, ignore "
        "this email.</p>" + _FOOTER["en"],
    ),
    (
        "public_check_magic_link",
        "de",
        "Ihre gespeicherten Prozessprüfungen",
        "<p>Hier ist Ihr Link zu allen Prozessprüfungen, die mit dieser "
        "Adresse gespeichert wurden.</p>"
        '<p><a href="{{ link_url }}">Meine Prüfungen öffnen</a></p>'
        "<p>Der Link ist 24 Stunden gültig. Wenn Sie ihn nicht angefordert "
        "haben, ignorieren Sie diese E-Mail.</p>" + _FOOTER["de"],
    ),
)

_CODES = ("public_check_confirm", "public_check_magic_link")


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "public_check_emails",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("locale", sa.String(length=5), nullable=False),
        _ts("consent_at", nullable=False),
        sa.Column(
            "marketing_opt_in",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        _ts("marketing_opt_in_at"),
        _ts("verified_at"),
        _ts("unsubscribed_at"),
        sa.Column("unsubscribe_token_hash", sa.String(length=64), nullable=False),
        sa.Column("confirm_token_hash", sa.String(length=64), nullable=True),
        _ts("confirm_expires_at"),
        sa.Column("magic_token_hash", sa.String(length=64), nullable=True),
        _ts("magic_expires_at"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("unsubscribe_token_hash"),
        sa.UniqueConstraint("confirm_token_hash"),
        sa.UniqueConstraint("magic_token_hash"),
    )
    op.add_column(
        "public_checks",
        sa.Column("email_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "public_checks",
        sa.Column("owner_key_hash", sa.String(length=64), nullable=True),
    )
    op.add_column("public_checks", _ts("moved_at"))
    op.add_column(
        "public_checks",
        sa.Column("moved_tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "public_checks_email_id_fkey",
        "public_checks",
        "public_check_emails",
        ["email_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "public_checks_moved_tenant_id_fkey",
        "public_checks",
        "tenants",
        ["moved_tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_public_checks_container_id", "public_checks", ["container_id"])
    op.create_index("ix_public_checks_email_id", "public_checks", ["email_id"])

    bind = op.get_bind()
    for code, locale, subject, body in _TEMPLATES:
        bind.execute(
            sa.text("""
                INSERT INTO notification_templates
                    (id, code, locale, subject_template, body_template,
                     notification_type, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :code, :locale, :subject, :body,
                     'email', now(), now())
                ON CONFLICT (code, locale) DO UPDATE SET
                    subject_template = EXCLUDED.subject_template,
                    body_template = EXCLUDED.body_template,
                    updated_at = now()
                """),
            {"code": code, "locale": locale, "subject": subject, "body": body},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code in _CODES:
        # No in-app rows are written for these codes, but the FK has no
        # ON DELETE clause: clear any before the templates.
        bind.execute(
            sa.text("""
                DELETE FROM notifications
                WHERE template_id IN (
                    SELECT id FROM notification_templates WHERE code = :code
                )
                """),
            {"code": code},
        )
        bind.execute(
            sa.text("DELETE FROM notification_templates WHERE code = :code"),
            {"code": code},
        )
    op.drop_index("ix_public_checks_email_id", table_name="public_checks")
    op.drop_index("ix_public_checks_container_id", table_name="public_checks")
    op.drop_constraint(
        "public_checks_moved_tenant_id_fkey", "public_checks", type_="foreignkey"
    )
    op.drop_constraint(
        "public_checks_email_id_fkey", "public_checks", type_="foreignkey"
    )
    op.drop_column("public_checks", "moved_tenant_id")
    op.drop_column("public_checks", "moved_at")
    op.drop_column("public_checks", "email_id")
    op.drop_column("public_checks", "owner_key_hash")
    op.drop_table("public_check_emails")
