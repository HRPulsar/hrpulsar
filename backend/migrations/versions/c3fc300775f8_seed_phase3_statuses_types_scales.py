"""seed_phase3_statuses_types_scales

Revision ID: c3fc300775f8
Revises: fc2bda23a969
Create Date: 2026-04-15 18:49:23.417316
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3fc300775f8"
down_revision: str | None = "fc2bda23a969"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Assessment statuses
    op.execute("""
        INSERT INTO assessment_statuses (id, code, title, sequence, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'draft', 'Draft', 0, now(), now()),
            (gen_random_uuid(), 'sent', 'Sent', 1, now(), now()),
            (gen_random_uuid(), 'in_progress', 'In Progress', 2, now(), now()),
            (gen_random_uuid(), 'summarizing', 'Summarizing', 3, now(), now()),
            (gen_random_uuid(), 'await_result', 'Awaiting Result', 4, now(), now()),
            (gen_random_uuid(), 'done', 'Done', 5, now(), now()),
            (gen_random_uuid(), 'cancelled', 'Cancelled', 99, now(), now())
    """)

    # Assessment types
    op.execute("""
        INSERT INTO assessment_types (id, code, title, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'self', 'Self Assessment', now(), now()),
            (gen_random_uuid(), '180', '180° Assessment', now(), now()),
            (gen_random_uuid(), '360', '360° Assessment', now(), now())
    """)

    # Default answer scale (5-point)
    op.execute("""
        INSERT INTO answer_scales (id, title, description, tenant_id, is_default, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'Standard 5-Point Scale', 'Default assessment scoring scale', NULL, true, now(), now())
    """)

    # Answer options for default scale
    op.execute("""
        INSERT INTO answer_options (id, scale_id, title, code, weight, description, sort_index, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            s.id,
            v.title,
            v.code,
            v.weight,
            v.description,
            v.sort_index,
            now(),
            now()
        FROM answer_scales s
        CROSS JOIN (VALUES
            ('N/A', 'na', 0, 'Not applicable or not observed', 0),
            ('Below Expectations', 'below', 1, 'Does not meet the expected level', 1),
            ('Meets Expectations', 'meets', 2, 'Meets the expected level', 2),
            ('Exceeds Expectations', 'exceeds', 3, 'Exceeds the expected level', 3),
            ('Outstanding', 'outstanding', 4, 'Significantly exceeds expectations', 4)
        ) AS v(title, code, weight, description, sort_index)
        WHERE s.is_default = true
    """)

    # Notification templates
    op.execute("""
        INSERT INTO notification_templates (id, code, subject_template, body_template, notification_type, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'assessment.sent', 'Assessment assigned: {{ assessment_title }}', '<p>Hi {{ recipient_name }},</p><p>You have been assigned to participate in assessment <b>{{ assessment_title }}</b>.</p><p>Deadline: {{ deadline }}</p>', 'email', now(), now()),
            (gen_random_uuid(), 'assessment.done', 'Assessment completed: {{ assessment_title }}', '<p>Hi {{ recipient_name }},</p><p>Assessment <b>{{ assessment_title }}</b> has been completed.</p>', 'email', now(), now()),
            (gen_random_uuid(), 'pdp.sent', 'Development plan assigned', '<p>Hi {{ recipient_name }},</p><p>A personal development plan has been created for you.</p><p>Deadline: {{ deadline }}</p>', 'email', now(), now()),
            (gen_random_uuid(), 'pdp.approved', 'Development plan approved', '<p>Hi {{ recipient_name }},</p><p>Your development plan has been approved.</p>', 'email', now(), now()),
            (gen_random_uuid(), 'pdp.returned', 'Development plan returned for revision', '<p>Hi {{ recipient_name }},</p><p>Your development plan has been returned for revision.</p>', 'email', now(), now()),
            (gen_random_uuid(), 'exam.assigned', 'Exam assigned: {{ exam_title }}', '<p>Hi {{ recipient_name }},</p><p>You have been assigned to exam <b>{{ exam_title }}</b>.</p><p>Deadline: {{ deadline }}</p>', 'email', now(), now()),
            (gen_random_uuid(), 'exam.done', 'Exam results: {{ exam_title }}', '<p>Hi {{ recipient_name }},</p><p>Your exam <b>{{ exam_title }}</b> results are ready. Score: {{ score }}/{{ max_score }}</p>', 'email', now(), now()),
            (gen_random_uuid(), 'invite', 'Welcome to {{ company_name }}', '<p>Hi {{ recipient_name }},</p><p>You have been invited to join <b>{{ company_name }}</b> on HRPulsar.</p>', 'email', now(), now()),
            (gen_random_uuid(), 'password.reset', 'Password reset request', '<p>Hi {{ recipient_name }},</p><p>Click the link below to reset your password.</p><p><a href="{{ reset_link }}">Reset Password</a></p>', 'email', now(), now())
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM answer_options WHERE scale_id IN (SELECT id FROM answer_scales WHERE is_default = true)"
    )
    op.execute("DELETE FROM answer_scales WHERE is_default = true")
    op.execute("DELETE FROM assessment_types")
    op.execute("DELETE FROM assessment_statuses")
    op.execute("DELETE FROM notification_templates")
