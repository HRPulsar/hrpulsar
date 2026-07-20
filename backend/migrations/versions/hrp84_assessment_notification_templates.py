"""HRP-84: notification templates for in-app assessment lifecycle bell.

Email subjects/bodies are still rendered by
``app.core.email_templates.render_assessment_*`` (free-form Russian copy).
The notification_templates rows here exist only so an in-app Notification
row can reference a template_id with a meaningful UI label — the bell
component reads ``notification.template.code`` + ``notification.context``
and renders its own short text per code.

Revision ID: hrp84inappnotif
Revises: hrp134profsess01
Create Date: 2026-05-31 10:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "hrp84inappnotif"
down_revision: str | None = "hrp134profsess01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TEMPLATES = [
    ("assessment.self_evaluate", "Evaluate yourself", "Please complete your assessment."),
    (
        "assessment.manager_evaluate",
        "Evaluate your employee",
        "Please evaluate {{employee_name}}.",
    ),
    (
        "assessment.evaluate_employee",
        "Evaluate employee",
        "Please complete the assessment.",
    ),
    (
        "assessment.self_completed",
        "Your assessment has completed",
        "Your assessment {{title}} is complete.",
    ),
    (
        "assessment.manager_completed",
        "Your employee assessment has completed",
        "Assessment for {{employee_name}} is complete.",
    ),
    (
        "assessment.self_cancelled",
        "Your assessment cancelled",
        "Your assessment {{title}} was cancelled.",
    ),
    (
        "assessment.manager_cancelled",
        "Your employee assessment cancelled",
        "Assessment for {{employee_name}} was cancelled.",
    ),
]


def upgrade() -> None:
    rows = ", ".join(
        f"(gen_random_uuid(), '{code}', '{subject}', '{body}', 'assessment', now(), now())"
        for code, subject, body in _TEMPLATES
    )
    op.execute(
        f"""
        INSERT INTO notification_templates
            (id, code, subject_template, body_template, notification_type, created_at, updated_at)
        VALUES {rows}
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in _TEMPLATES)
    op.execute(
        f"DELETE FROM notification_templates WHERE code IN ({codes})"
    )
