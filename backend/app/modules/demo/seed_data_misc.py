"""Miscellaneous fixtures for the demo seed (HRP-281 — S8).

Three buckets of small, page-finishing rows:

1. Tenant-scoped DictionaryItem rows in fresh types (``language``,
   ``certification``, ``office_location``) so the Settings →
   Dictionaries page has more than the company's own grade + spec
   catalog, plus the three types the page ships its own tabs for
   (``role``, ``goal``, ``project`` — see
   ``dictionary/schemas.py``). Those three used to render empty, so
   the demo's Dictionaries page answered "what goes in here?" with
   nothing (HRP-713).

2. In-app Notification rows for the demo owner so the notification
   bell isn't empty. Each row maps to an existing NotificationTemplate
   code shipped by migration ``c3fc300775f8``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Custom dictionaries
# ---------------------------------------------------------------------------

CUSTOM_DICTIONARIES: list[dict] = [
    {
        "type": "language",
        "items": [
            {"title": "English", "sort_index": 10},
            {"title": "Russian", "sort_index": 20},
            {"title": "Spanish", "sort_index": 30},
            {"title": "German", "sort_index": 40},
            {"title": "French", "sort_index": 50},
        ],
    },
    {
        "type": "certification",
        "items": [
            {"title": "AWS Solutions Architect — Associate", "sort_index": 10},
            {"title": "CISSP", "sort_index": 20},
            {"title": "PMP", "sort_index": 30},
            {"title": "GCP Professional Cloud Architect", "sort_index": 40},
            {"title": "Certified Scrum Master", "sort_index": 50},
        ],
    },
    {
        "type": "office_location",
        "items": [
            {"title": "Remote", "sort_index": 10},
            {"title": "Berlin", "sort_index": 20},
            {"title": "London", "sort_index": 30},
            {"title": "New York", "sort_index": 40},
        ],
    },
    # The three types the Dictionaries page gives its own tab. They are
    # the vocabulary the rest of the product points at — a role somebody
    # holds beside their position, the goal a development plan works
    # toward, the project they are staffed on — so an empty tab reads as
    # a broken page rather than an unused feature.
    {
        "type": "role",
        "items": [
            {"title": "Team lead", "sort_index": 10},
            {"title": "Mentor", "sort_index": 20},
            {"title": "Tech lead", "sort_index": 30},
            {"title": "Product owner", "sort_index": 40},
            {"title": "Incident commander", "sort_index": 50},
        ],
    },
    {
        "type": "goal",
        "items": [
            {"title": "Promotion to senior", "sort_index": 10},
            {"title": "Lead a cross-team project", "sort_index": 20},
            {"title": "Professional certification", "sort_index": 30},
            {"title": "Mentor a new hire to independence", "sort_index": 40},
            {"title": "Speak at an industry conference", "sort_index": 50},
        ],
    },
    {
        "type": "project",
        "items": [
            {"title": "CRM migration", "sort_index": 10},
            {"title": "Mobile app launch", "sort_index": 20},
            {"title": "Onboarding revamp", "sort_index": 30},
            {"title": "Data platform rebuild", "sort_index": 40},
            {"title": "Security audit remediation", "sort_index": 50},
        ],
    },
]


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------
#
# Each entry references a template by ``template_code`` (origin from the
# notification migration). Status / is_read are spread so the bell shows
# a mix of unread and recently-read entries.

NOTIFICATIONS: list[dict] = [
    {
        "template_code": "assessment.sent",
        "subject_data": "Q1 360° plan — Engineering Backend",
        "is_read": False,
        "status": "sent",
        "days_ago": 0,
    },
    {
        "template_code": "assessment.done",
        "subject_data": "Q4 360° review — Anna Rising",
        "is_read": False,
        "status": "sent",
        "days_ago": 1,
    },
    {
        "template_code": "pdp.sent",
        "subject_data": "Growth path Q1–Q2 — Marcus Johnson",
        "is_read": True,
        "status": "sent",
        "days_ago": 2,
    },
    {
        "template_code": "pdp.approved",
        "subject_data": "Plan completed — Anna Rising (Q3)",
        "is_read": True,
        "status": "sent",
        "days_ago": 4,
    },
    {
        "template_code": "pdp.returned",
        "subject_data": "Returned — please expand items",
        "is_read": False,
        "status": "sent",
        "days_ago": 1,
    },
    {
        "template_code": "exam.assigned",
        "subject_data": "Engineering Onboarding Quiz",
        "is_read": False,
        "status": "sent",
        "days_ago": 0,
    },
    {
        "template_code": "exam.done",
        "subject_data": "Python Fundamentals",
        "is_read": True,
        "status": "sent",
        "days_ago": 3,
    },
    {
        "template_code": "assessment.sent",
        "subject_data": "Q1 self assessment — Yara Saito",
        "is_read": True,
        "status": "sent",
        "days_ago": 5,
    },
    {
        "template_code": "pdp.approved",
        "subject_data": "Cancelled — superseded by Q1 plan",
        "is_read": True,
        "status": "sent",
        "days_ago": 7,
    },
    {
        "template_code": "exam.assigned",
        "subject_data": "Security & Compliance Annual",
        "is_read": False,
        "status": "sent",
        "days_ago": 0,
    },
]
