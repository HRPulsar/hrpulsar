"""Moderated signup module (HRP-259..262 — M-wave).

Replaces the public waitlist. A landing visitor submits a small form
(email + name + company + role), confirms via emailed link, then a
team member approves or rejects from Slack. On approve we provision a
real Tenant + User pair and email a one-time magic-login link.
"""
