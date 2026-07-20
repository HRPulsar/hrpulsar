"""Miscellaneous fixtures for the demo seed (HRP-281 — S8).

Three buckets of small, page-finishing rows:

1. Tenant-scoped DictionaryItem rows in fresh types (``language``,
   ``certification``, ``office_location``) so the Settings →
   Dictionaries page has more than the company's own grade + spec
   catalog.

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
        "subject_data": "Q4 360° review — Carlos Mendez",
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
        "subject_data": "Plan completed — Carlos Mendez (Q3)",
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
