"""The anonymous process check (HRP-922, epic HRP-918).

One row per check a visitor of the public service starts: their text and
answers, the sandbox container and decomposition run it was analysed in,
and the result frozen as a snapshot once the run is through - the page
reads the snapshot, never the container, so neither a catalog revision nor
a cleanup of the sandbox changes what a shared link shows.

The row belongs to no tenant: the visitor has no account, and the sandbox
company the analysis runs in is one for the whole platform (``service``).
The link is a random token of which only the sha256 is stored. No IP and
no contact data on the check: the limits of HRP-923 live in Redis, and the
email a visitor saves a check with (HRP-926) is a row of its own
(``PublicCheckEmail``) the check points at.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import BaseModel


class PublicCheck(BaseModel):
    __tablename__ = "public_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'error')",
            name="ck_public_checks_status",
        ),
        # The cleanup of expired checks (HRP-923) scans by it.
        Index("ix_public_checks_expires_at", "expires_at"),
        # The purge's anti-join over sandbox containers (HRP-923).
        Index("ix_public_checks_container_id", "container_id"),
        Index("ix_public_checks_email_id", "email_id"),
    )

    # sha256 of the link token, hex.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # sha256 of the owner key (HRP-926): the link token lets anyone it is
    # shared with read the result; only the owner key, handed once to the
    # browser that ran the check, lets a visitor save it to an address.
    # NULL - a check from before the key, which cannot be saved.
    owner_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Industry, team size, frequency, hourly rate and currency, as given.
    answers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # ``en`` or ``de`` - the request schema holds the list, so a new
    # language costs no migration.
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    # utm_source / medium / campaign / content / term of the visit (HRP-931).
    utm: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # The description was dictated by voice (HRP-947): "try again" sends it
    # the same way, so the new run's model is told so too.
    dictated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    container_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_containers.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_decomposition_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ``schemas.CheckResult`` as JSON, written once with ``status='ready'``.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # NULL = kept without a term: set by the click of the check's own
    # confirmation letter - the one proof the address's owner wants it.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The email the visitor saved the check with (HRP-926). Deleting the
    # address deletes its checks; their containers go with the purge.
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public_check_emails.id", ondelete="CASCADE"),
        nullable=True,
    )
    # The confirmation letter of this check's save (HRP-926): sha256 of its
    # token, 7 days. Only the click of the address's owner keeps the check
    # (its term goes) - a save proves nothing about owning the address,
    # confirmed or not. A new save of the check replaces the token; a save
    # of another check never touches it.
    confirm_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    confirm_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The save's opt-in to product news, written to the address only by
    # that click: a stranger's save never opts an address in.
    confirm_marketing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # When and into which workspace the check moved as a Coverage process
    # (HRP-927, ``move``); a moved check moves no more.
    moved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    moved_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )


class PublicCheckEmail(BaseModel):
    """An address a visitor saved checks with (HRP-926), one row per address.

    ``email`` is lowercased. ``locale`` and ``consent_at`` come from the save
    that created the row - ``locale`` is the language of every letter to the
    address. A save proves nothing about owning the address, so it changes
    nothing on an existing row: the marketing opt-in is set by the click of
    a check's confirmation letter (``PublicCheck.confirm_*``), which also
    sets ``verified_at``. Nothing clears ``unsubscribed_at`` or opts an
    unsubscribed address back in. Marketing, once there is any, goes only to
    confirmed addresses with ``marketing_opt_in`` and no ``unsubscribed_at``.

    Tokens are stored as sha256 only. The "my checks" link (``magic_*``, 24
    hours) is random, the latest one issued wins. The unsubscribe token is
    permanent: an HMAC of the row id, so every letter carries the same one
    without the row keeping it.
    """

    __tablename__ = "public_check_emails"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    locale: Mapped[str] = mapped_column(String(5), nullable=False)
    consent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    marketing_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    marketing_opt_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unsubscribe_token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    magic_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    magic_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PublicCheckEvent(Base):
    """A funnel counter of the public check (HRP-931): how many times
    ``event`` happened on ``day`` (UTC) for visits from ``source``.

    The client steps (``opened``, ``started``, ``shared``) count here only.
    The steps a check row records (``result``, ``email``, ``confirmed``,
    ``moved``) are counted from the rows while they live, and land here when
    the purge or a visitor's "delete my data" removes them - by the day the
    check was created. No visitor, IP or token: a counter per day, step and
    source. ``source`` is normalised (``funnel.normalise_source``)."""

    __tablename__ = "public_check_events"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    event: Mapped[str] = mapped_column(String(20), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, nullable=False)
