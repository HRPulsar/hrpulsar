"""Wire schemas of the public process check (HRP-922).

The request is the trust boundary of an anonymous service: every string has
a length limit here (the rate limit, the captcha and the daily budget of
HRP-923 sit in the router). The result is the contract of the result page (HRP-925): numbers,
enums and catalog codes only - no prose of ours, the page builds every
sentence with ``t()``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

# The only source of the description limits: the input page (HRP-924)
# repeats both numbers as constants of its own - change them together.
# About a page of text, room for a dictated description (HRP-947); the
# model's answer and the cost of a check grow with the input.
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 4000
ANSWER_MAX = 100
UTM_MAX = 200
# Cloudflare documents a Turnstile token as at most 2048 characters.
TURNSTILE_TOKEN_MAX = 2048
# ``secrets.token_urlsafe(32)`` is 43 characters; room, not a format check.
OWNER_KEY_MAX = 128

Locale = Literal["en", "de"]
Frequency = Literal["daily", "weekly", "monthly", "quarterly", "yearly", "ad_hoc"]
Status = Literal["pending", "running", "ready", "error"]
# The engine's own words (``work.coverage``): ``moves`` - an agent does the
# step alone; ``to_review`` - an AI draft a person checks; ``stays`` - people.
Bucket = Literal["moves", "to_review", "stays"]
Mode = Literal[
    "automatable",
    "draft_then_review",
    "review_required",
    "blocked_judgment",
    "blocked_physical",
]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=ANSWER_MAX)]
UtmValue = Annotated[str, StringConstraints(strip_whitespace=True, max_length=UTM_MAX)]


class Answers(BaseModel):
    """The optional questions of the input page. Industry, team size and
    frequency go to the model with the description; the rate only prices
    the result."""

    model_config = ConfigDict(extra="forbid")

    industry: Short | None = None
    team_size: int | None = Field(default=None, ge=1, le=100_000)
    frequency: Frequency | None = None
    hourly_rate: float | None = Field(default=None, gt=0, le=100_000)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")


class Utm(BaseModel):
    """The campaign the visit came from, for the funnel (HRP-931). Unknown
    keys are dropped, not refused: a tracking parameter must never cost a
    visitor the check."""

    model_config = ConfigDict(extra="ignore")

    source: UtmValue | None = None
    medium: UtmValue | None = None
    campaign: UtmValue | None = None
    content: UtmValue | None = None
    term: UtmValue | None = None


class CheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=DESCRIPTION_MIN,
            max_length=DESCRIPTION_MAX,
        ),
    ]
    answers: Answers = Field(default_factory=Answers)
    # The language of the breakdown - the steps' titles and descriptions.
    locale: Locale = "en"
    utm: Utm | None = None
    # The captcha (HRP-923): sent by the page only when its Turnstile
    # widget gave a token; required while the server has a secret.
    turnstile_token: str | None = Field(default=None, max_length=TURNSTILE_TOKEN_MAX)
    # The field holds text dictated by voice (HRP-947): the model is told it
    # may read misheard words (``service.process_text``).
    dictated: bool = False


class CheckCreated(BaseModel):
    """``token`` is the key to read the check: the link of the result page,
    which the visitor may share. ``owner_key`` is the key to save it by
    email (HRP-926) - for the browser that ran the check only, never in
    ``CheckRead``. Both are shown this once and never again."""

    token: str
    owner_key: str
    status: Status
    expires_at: datetime | None


# --- The result (HRP-925) ----------------------------------------------------


class StepReason(BaseModel):
    """Why the step is in its bucket, machine-readable. ``mode`` is the
    automation mode the engine derived; ``codes`` are the capability codes
    that decided it (labels: ``reference.primitive.<code lowercased>`` in
    the frontend catalogs):

    * ``automatable`` - every capability of the step, all strong for AI;
    * ``draft_then_review`` - the capabilities AI only drafts;
    * ``review_required`` - none: ``responsibility`` (``formal`` or
      ``regulatory``) or ``output_type`` (``external_change``) decided it;
    * ``blocked_judgment`` - the capabilities that need human judgement;
    * ``blocked_physical`` - the physical or presence capabilities.

    ``mode`` is null on a step with no capability at all."""

    mode: Mode | None
    codes: list[str]
    responsibility: Literal["none", "reputational", "formal", "regulatory"]
    output_type: Literal["draft", "external_change"]


class ResultStep(BaseModel):
    """One step as the model wrote it, in the language of the check.
    ``hours_per_year`` is ``hours_per_run x runs_per_year``; null when the
    model gave no estimate - the step then counts in no hour and no money
    figure (``Hours.unestimated``)."""

    position: int
    title: str
    description: str | None
    codes: list[str]
    hours_per_run: float | None
    runs_per_year: int | None
    hours_per_year: float | None
    reason: StepReason


class Buckets(BaseModel):
    """The three lists, each in process order."""

    moves: list[ResultStep]
    to_review: list[ResultStep]
    stays: list[ResultStep]


class Hours(BaseModel):
    """Yearly hours of the estimated steps in scope. ``to_review_after`` is
    what the people who check AI drafts keep of ``to_review`` (half by
    default); ``freed`` = ``moves`` + ``to_review`` - ``to_review_after``.
    ``unestimated`` counts the steps in scope without an estimate."""

    total: float
    moves: float
    to_review: float
    stays: float
    to_review_after: float
    freed: float
    unestimated: int


class Shares(BaseModel):
    """Percent of ``Hours.total`` per bucket. The headline figure - the
    share of the yearly hours an agent takes - is ``moves``."""

    moves: float
    to_review: float
    stays: float


class Money(BaseModel):
    """``Hours`` priced at the visitor's hourly rate, per year, in
    ``currency``."""

    total: float
    moves: float
    to_review: float
    stays: float
    to_review_after: float
    freed: float
    currency: str


class CheckResult(BaseModel):
    """The frozen result of a check.

    ``shares`` is null when the engine shows no percentages (fewer than four
    steps in scope, or no estimate on a step an agent could take); the page
    then leads with the lists. ``money`` is null without an hourly rate.
    ``preliminary`` - nobody has reviewed the breakdown, so every figure is
    an estimate; always true for an anonymous check, the field exists for
    the saved and moved flows (HRP-926, HRP-927). ``out_of_scope`` are the steps with no capability AI
    could apply at all (physical work, or nothing to tag): in no bucket and
    no figure, listed so that no step of the process goes missing."""

    schema_version: Literal[1] = 1
    preliminary: bool
    catalog_version: str
    shares: Shares | None
    hours: Hours
    money: Money | None
    buckets: Buckets
    out_of_scope: list[ResultStep]


class CheckRead(BaseModel):
    """What the polling page and the result page read.

    ``phase`` drives the progress bar while the check runs: ``splitting``
    (the model cuts the text into steps), ``classifying`` (it tags them),
    ``finishing`` (the figures are computed); null while queued. On
    ``error``, ``error_code`` is a machine code (``service_error``,
    ``overload``, ``output_truncated``, ``reaped_stuck``, ...).

    ``title`` is the process's name as the sandbox container holds it: the
    description's first line, cut (HRP-928, the share card)."""

    status: Status
    phase: Literal["splitting", "classifying", "finishing"] | None
    error_code: str | None
    locale: Locale
    title: str
    description: str
    answers: Answers
    # The visit's campaign (HRP-931): "try again" carries it into the new
    # check, a share beacon names it.
    utm: Utm | None = None
    # Dictated by voice (HRP-947): "try again" sends the input the same way.
    dictated: bool = False
    created_at: datetime
    expires_at: datetime | None
    result: CheckResult | None


# --- Saved by email (HRP-926) -------------------------------------------------


class SaveRequest(BaseModel):
    """Keep a check: the address it is saved with, the consent to process
    it (required - ``false`` or missing is a 422), a separate optional
    marketing opt-in, and the interface language the address's letters go
    out in. The captcha as on ``CheckCreate``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    consent: Literal[True]
    marketing: bool = False
    locale: Locale = "en"
    # ``CheckCreated.owner_key``: without it (a shared link) - 403.
    owner_key: str | None = Field(default=None, max_length=OWNER_KEY_MAX)
    turnstile_token: str | None = Field(default=None, max_length=TURNSTILE_TOKEN_MAX)


class SaveResult(BaseModel):
    """Always ``confirm``: a letter for this check is on its way (within
    the address's hourly cap), and the check keeps its term until it is
    clicked - whether the address was confirmed before is never said."""

    status: Literal["confirm"]


class LinkRequest(BaseModel):
    """A visitor asks for their link again. The answer never says whether
    the address is known."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    turnstile_token: str | None = Field(default=None, max_length=TURNSTILE_TOKEN_MAX)


class LinkSent(BaseModel):
    status: Literal["sent"] = "sent"


class Confirmed(BaseModel):
    status: Literal["confirmed"] = "confirmed"


class Unsubscribed(BaseModel):
    status: Literal["unsubscribed"] = "unsubscribed"


class SavedCheck(BaseModel):
    """One row of "my checks". ``share_moves`` is the headline figure of a
    ready result with percentages, else null. ``id`` opens the result
    through the same "my checks" link - the check's own link token is not
    stored and cannot be shown."""

    id: uuid.UUID
    created_at: datetime
    title: str
    status: Status
    share_moves: float | None
    expires_at: datetime | None
    # HRP-927: the check is a process of a workspace already.
    moved: bool = False


class SavedChecks(BaseModel):
    """``account`` - an active user of this email exists: "move to
    HRPulsar" signs in rather than registers (HRP-927). Only the holder of
    the address's link reads it."""

    email: str
    checks: list[SavedCheck]
    account: bool = False


# --- Moved into a workspace (HRP-927) -----------------------------------------


class Moved(BaseModel):
    """How many checks became processes of the caller's workspace; 0 when
    every ready check of the address is in a workspace already.
    ``skipped`` - checks that could not become a process (logged); they
    stay unmoved."""

    moved: int
    skipped: int = 0


# --- Dictation (HRP-947) ------------------------------------------------------


class Transcript(BaseModel):
    """The text of a recording, for the visitor to correct in the field.
    ``language`` as the provider detected it (Whisper names it in full,
    ``english``), null when it did not say. Empty ``text`` - no speech
    heard."""

    text: str
    language: str | None


# --- Funnel beacons (HRP-931) -------------------------------------------------

# The client steps of the funnel; the others are counted from check rows.
FunnelEvent = Literal["opened", "started", "shared"]


class CheckEvent(BaseModel):
    """A page beacon. Anything else the page sends (a token, say) is
    dropped, never stored; ``utm`` is the visit's or the shared check's."""

    model_config = ConfigDict(extra="ignore")

    event: FunnelEvent
    utm: Utm | None = None
