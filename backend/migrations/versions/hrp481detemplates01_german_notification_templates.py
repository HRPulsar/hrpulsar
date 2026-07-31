"""i18n F7 (HRP-481): German NotificationTemplate rows.

Replaces the English copies seeded per code by ``hrp478emaildb01`` with
real German strings. The INSERT selects the en sibling so a code absent
from an installation is skipped, and the conflict target is
``(code, locale)`` — the only allowed one after F4. ``downgrade``
restores the F4 state (de rows = English copies of their en sibling).

Revision ID: hrp481detemplates01
Revises: hrp491mergewl1
Create Date: 2026-07-30 15:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hrp481detemplates01"
down_revision: str | None = "hrp491mergewl1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# code -> (subject_template, body_template), German. Jinja placeholders
# were verified byte-identical to the en rows by the generator script at
# authoring time (scratchpad f7/gen_template_migration.py) and against
# the live dev DB; there is no permanent scan test for this table.
GERMAN_TEMPLATES: dict[str, tuple[str, str]] = {
    'assessment.done': (
        'Bewertung abgeschlossen: {{ assessment_title }}',
        '<p>Hallo {{ recipient_name }},</p><p>Die Bewertung <b>{{ assessment_title }}</b> wurde abgeschlossen.</p>',
    ),
    'assessment.evaluate_employee': (
        'Mitarbeiter bewerten',
        'Bitte schließen Sie die Bewertung ab.',
    ),
    'assessment.manager_cancelled': (
        'Bewertung Ihres Mitarbeiters abgebrochen',
        'Die Bewertung für {{employee_name}} wurde abgebrochen.',
    ),
    'assessment.manager_completed': (
        'Bewertung Ihres Mitarbeiters ist abgeschlossen',
        'Die Bewertung für {{employee_name}} ist abgeschlossen.',
    ),
    'assessment.manager_evaluate': (
        'Bewerten Sie Ihren Mitarbeiter',
        'Bitte bewerten Sie {{employee_name}}.',
    ),
    'assessment.self_cancelled': (
        'Ihre Bewertung wurde abgebrochen',
        'Ihre Bewertung {{title}} wurde abgebrochen.',
    ),
    'assessment.self_completed': (
        'Ihre Bewertung ist abgeschlossen',
        'Ihre Bewertung {{title}} ist abgeschlossen.',
    ),
    'assessment.self_evaluate': (
        'Selbsteinschätzung ausfüllen',
        'Bitte schließen Sie Ihre Bewertung ab.',
    ),
    'assessment.sent': (
        'Bewertung zugewiesen: {{ assessment_title }}',
        '<p>Hallo {{ recipient_name }},</p><p>Sie wurden zur Teilnahme an der Bewertung <b>{{ assessment_title }}</b> eingeladen.</p><p>Frist: {{ deadline }}</p>',
    ),
    'competence_generation_error': (
        'KI-Kompetenzgenerierung fehlgeschlagen',
        '<p>Hallo {{ recipient_name }},</p><p>Ihre Sitzung zur Kompetenzgenerierung wurde mit einem Fehler beendet: {{ error_message }}.</p>',
    ),
    'competence_generation_ready': (
        'KI-Kompetenzgenerierung ist bereit',
        '<p>Hallo {{ recipient_name }},</p><p>Ihre Sitzung zur Kompetenzgenerierung ist abgeschlossen. Öffnen Sie die Kompetenzbibliothek, um die Vorschläge zu prüfen und zu übernehmen.</p>',
    ),
    'employee_inactive': (
        'Ihr Konto wurde deaktiviert',
        '<p>Hallo {{ employee_name }},</p><p>Ihr Konto wurde als <b>inaktiv</b> markiert. Die Anmeldung ist deaktiviert, solange dieser Status gilt.</p><p>Bei Fragen wenden Sie sich an Ihren Administrator.</p>',
    ),
    'employee_reactivated': (
        'Ihr Konto wurde reaktiviert',
        '<p>Hallo {{ employee_name }},</p><p>Ihr Konto ist wieder <b>aktiv</b> — Sie können sich anmelden und im System weiterarbeiten.</p>',
    ),
    'employee_terminated': (
        'Ihr Arbeitsverhältnis wurde beendet',
        '<p>Hallo {{ employee_name }},</p><p>Ihr Arbeitsverhältnis wurde als <b>ausgeschieden</b> markiert. Sie haben keinen Zugriff mehr auf das System.</p><p>Sollte dies ein Fehler sein, wenden Sie sich an Ihren Administrator.</p>',
    ),
    'exam.assigned': (
        'Prüfung zugewiesen: {{ exam_title }}',
        '<p>Hallo {{ recipient_name }},</p><p>Sie wurden der Prüfung <b>{{ exam_title }}</b> zugewiesen.</p><p>Frist: {{ deadline }}</p>',
    ),
    'exam.done': (
        'Prüfungsergebnisse: {{ exam_title }}',
        '<p>Hallo {{ recipient_name }},</p><p>Die Ergebnisse Ihrer Prüfung <b>{{ exam_title }}</b> liegen vor. Punktzahl: {{ score }}/{{ max_score }}</p>',
    ),
    'invite': (
        'Willkommen bei {{ company_name }}',
        '<p>Hallo {{ recipient_name }},</p><p>Sie wurden eingeladen, <b>{{ company_name }}</b> auf HRPulsar beizutreten.</p>',
    ),
    'password.reset': (
        'Anfrage zum Zurücksetzen des Passworts',
        '<p>Hallo {{ recipient_name }},</p><p>Klicken Sie auf den Link unten, um Ihr Passwort zurückzusetzen.</p><p><a href="{{ reset_link }}">Passwort zurücksetzen</a></p>',
    ),
    'pdp.approved': (
        'Entwicklungsplan genehmigt',
        '<p>Hallo {{ recipient_name }},</p><p>Ihr Entwicklungsplan wurde genehmigt.</p>',
    ),
    'pdp.returned': (
        'Entwicklungsplan zur Überarbeitung zurückgegeben',
        '<p>Hallo {{ recipient_name }},</p><p>Ihr Entwicklungsplan wurde zur Überarbeitung zurückgegeben.</p>',
    ),
    'pdp.sent': (
        'Entwicklungsplan zugewiesen',
        '<p>Hallo {{ recipient_name }},</p><p>Für Sie wurde ein persönlicher Entwicklungsplan erstellt.</p><p>Frist: {{ deadline }}</p>',
    ),
    'recruitment.ai_task_failed': (
        'KI-Aufgabe im Recruiting fehlgeschlagen',
        '<p>Eine KI-Hintergrundaufgabe ist fehlgeschlagen: {{ task_type }}{% if error %} — {{ error }}{% endif %}.</p>',
    ),
    'recruitment.candidate_attached': (
        'Neuer Kandidat für {{ vacancy_title }}',
        '<p>{{ candidate_name }} wurde der Stelle <b>{{ vacancy_title }}</b> zugeordnet.</p>',
    ),
    'recruitment.candidate_stage_changed': (
        '{{ candidate_name }} in {{ stage_name }} verschoben',
        '<p>{{ candidate_name }} befindet sich bei der Stelle <b>{{ vacancy_title }}</b> jetzt in der Phase <b>{{ stage_name }}</b>.</p>',
    ),
    'recruitment.consent_signed': (
        'Einwilligung unterschrieben: {{ candidate_name }}',
        '<p>{{ candidate_name }} hat das Einwilligungsformular für das Recruiting unterschrieben.</p>',
    ),
    'recruitment.interview_analysis_ready': (
        'KI-Analyse bereit: {{ candidate_name }}',
        '<p>Die KI-Analyse des Interviews mit <b>{{ candidate_name }}</b> ist abgeschlossen.</p>',
    ),
    'recruitment.interview_scheduled': (
        'Interview mit {{ candidate_name }} geplant',
        '<p>Sie wurden für das Interview mit <b>{{ candidate_name }}</b>{% if interview_date %} am {{ interview_date }}{% endif %} eingeteilt.</p>',
    ),
    'recruitment.interview_transcript_ready': (
        'Transkript bereit: {{ candidate_name }}',
        '<p>Das Interview-Transkript für <b>{{ candidate_name }}</b> steht zur Überprüfung bereit.</p>',
    ),
    'recruitment.invite_completed': (
        'Bewertung abgegeben von {{ evaluator_name }}',
        '<p>{{ evaluator_name }} hat eine Bewertung für <b>{{ candidate_name }}</b> abgegeben.</p>',
    ),
    'recruitment.question_set_failed': (
        'Fragengenerierung fehlgeschlagen: {{ candidate_name }}',
        '<p>Die KI-Fragengenerierung für <b>{{ candidate_name }}</b> ist fehlgeschlagen. Öffnen Sie die Kandidatenseite, um es erneut zu versuchen.</p>',
    ),
    'recruitment.question_set_ready': (
        'Interviewfragen bereit: {{ candidate_name }}',
        '<p>Ein neues Fragenset für das Interview mit <b>{{ candidate_name }}</b> steht zur Überprüfung bereit.</p>',
    ),
    'recruitment.report_generated': (
        'Bericht bereit: {{ vacancy_title }}',
        '<p>Ihr konsolidierter Bericht für <b>{{ vacancy_title }}</b> steht zum Herunterladen bereit.</p>',
    ),
    'recruitment.report_shared': (
        '{{ shared_by_name }} hat einen Recruiting-Bericht geteilt',
        "<p>Sie haben einen temporären Link zu einem Recruiting-Bericht für <b>{{ vacancy_title }}</b> erhalten.</p><p><a href='{{ share_url }}'>Bericht öffnen</a></p><p>Der Link läuft am {{ expires_at }} ab.</p>",
    ),
    'recruitment.vacancy_assigned': (
        'Stelle zugewiesen: {{ vacancy_title }}',
        '<p>Sie wurden als Verantwortlicher der Stelle <b>{{ vacancy_title }}</b> zugewiesen.</p>',
    ),
}

_UPSERT = sa.text("""
    INSERT INTO notification_templates
        (id, code, locale, subject_template, body_template,
         notification_type, created_at, updated_at)
    SELECT gen_random_uuid(), t.code, 'de', :subject, :body,
           t.notification_type, now(), now()
    FROM notification_templates t
    WHERE t.code = :code AND t.locale = 'en'
    ON CONFLICT (code, locale) DO UPDATE SET
        subject_template = EXCLUDED.subject_template,
        body_template = EXCLUDED.body_template,
        updated_at = now()
""")

_RESTORE_EN_COPY = sa.text("""
    UPDATE notification_templates d
    SET subject_template = e.subject_template,
        body_template = e.body_template,
        updated_at = now()
    FROM notification_templates e
    WHERE d.code = :code AND d.locale = 'de'
      AND e.code = d.code AND e.locale = 'en'
""")


def upgrade() -> None:
    conn = op.get_bind()
    for code, (subject, body) in GERMAN_TEMPLATES.items():
        conn.execute(_UPSERT, {"code": code, "subject": subject, "body": body})


def downgrade() -> None:
    conn = op.get_bind()
    for code in GERMAN_TEMPLATES:
        conn.execute(_RESTORE_EN_COPY, {"code": code})
