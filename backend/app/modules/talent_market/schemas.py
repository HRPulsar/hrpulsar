from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field, model_validator

# HRP-92: spec allows start_date in [today-5y, today+5y] and end_date in
# [start_date, today+5y]. Bounds are enforced server-side; the UI clamps
# the date pickers to the same window.
_DATE_WINDOW_YEARS = 5


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _validate_date_window(
    start: date | None, end: date | None
) -> tuple[date | None, date | None]:
    today = _today()
    lower = today - timedelta(days=_DATE_WINDOW_YEARS * 365)
    upper = today + timedelta(days=_DATE_WINDOW_YEARS * 365)
    if start is not None and (start < lower or start > upper):
        raise ValueError("start_date out of allowed range (±5 years from today)")
    if end is not None:
        if start is not None and end < start:
            raise ValueError("end_date must be on or after start_date")
        if end > upper:
            raise ValueError("end_date out of allowed range (+5 years from today)")
    return start, end


class TalentCardCreate(BaseModel):
    title: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=250)
    card_type: str = Field(pattern="^(vacancy|talent|project)$")
    division_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    # HRP-128: card-level Match% (50..100). Drives the Required competencies
    # matcher threshold for every competence on the card.
    match_percent: int = Field(default=80, ge=50, le=100)

    @model_validator(mode="after")
    def _check_dates(self) -> TalentCardCreate:
        _validate_date_window(self.start_date, self.end_date)
        return self


class TalentCardUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=250)
    division_id: uuid.UUID | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    # HRP-128: editable until publish — service enforces the publish-lock.
    match_percent: int | None = Field(default=None, ge=50, le=100)

    @model_validator(mode="after")
    def _check_dates(self) -> TalentCardUpdate:
        if self.start_date is not None or self.end_date is not None:
            _validate_date_window(self.start_date, self.end_date)
        return self


class TalentCardRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    card_type: str
    status: str
    author_id: uuid.UUID
    division_id: uuid.UUID | None
    is_published: bool
    tenant_id: uuid.UUID
    published_at: datetime | None
    closed_at: datetime | None
    # HRP-92 REDO: assessment-style terminal dates. Both default to None on
    # active cards; populated when the matching transition fires.
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    start_date: date
    end_date: date | None
    match_percent: int
    created_at: datetime
    # HRP-242: stamp of the last Candidates recompute (auto-pool or
    # Change-candidates save). The UI renders "today / yesterday /
    # Month dd" in the Candidates block header. NULL when the card has
    # never been recomputed (no Required block ever set).
    last_matched_at: datetime | None = None
    # HRP-213: True when the current viewer (as an employee) has reacted
    # on this card. Stamps the "Reacted" chip on the card preview tile.
    # Always False for viewers that aren't candidates.
    reacted_by_me: bool = False
    model_config = {"from_attributes": True}


class TalentCardDetail(TalentCardRead):
    specializations: list[SpecializationLink] = []
    competences: list[CompetenceLink] = []
    requirements: list[RequirementRead] = []
    candidates: list[CandidateRead] = []


class SearchRequest(BaseModel):
    card_type: str | None = None
    status: str | None = None
    specialization_id: uuid.UUID | None = None
    division_id: uuid.UUID | None = None
    skip: int = 0
    limit: int = 50


class SpecializationLink(BaseModel):
    id: uuid.UUID
    specialization_id: uuid.UUID
    grade_id: uuid.UUID | None
    min_experience_years: int | None = None
    model_config = {"from_attributes": True}


class CompetenceLink(BaseModel):
    id: uuid.UUID
    competence_id: uuid.UUID
    skill_level_id: uuid.UUID | None
    match_percent: int | None = None
    model_config = {"from_attributes": True}


class RequiredSpecializationCreate(BaseModel):
    """Required spec for a Talent Market card (HRP-87).

    `grade_id` is required by the UI even though the column is nullable —
    the validation lives here so the existing `TalentCardSpecialization`
    rows (HRP-32 pre-rewrite) don't get retroactively broken.
    """

    specialization_id: uuid.UUID
    grade_id: uuid.UUID
    min_experience_years: int | None = Field(default=None, ge=0)


class RequiredSpecializationUpdate(BaseModel):
    specialization_id: uuid.UUID
    grade_id: uuid.UUID
    min_experience_years: int | None = Field(default=None, ge=0)


class RequiredCompetenceItem(BaseModel):
    competence_id: uuid.UUID
    skill_level_id: uuid.UUID


class RequiredCompetenceBulkCreate(BaseModel):
    """HRP-128: dialog payload, now "set/replace" — items NOT in the list are
    removed. Match% lives on the card itself (TalentCard.match_percent), no
    longer per-row.
    """

    items: list[RequiredCompetenceItem] = Field(min_length=1)


class RequiredCompetenceUpdate(BaseModel):
    competence_id: uuid.UUID
    skill_level_id: uuid.UUID


class RequirementCreate(BaseModel):
    description: str = Field(max_length=500)
    min_experience_years: int | None = None


class RequirementRead(BaseModel):
    id: uuid.UUID
    description: str
    min_experience_years: int | None
    model_config = {"from_attributes": True}


class CandidateAdd(BaseModel):
    employee_id: uuid.UUID


class CandidateBulkAdd(BaseModel):
    """HRP-95: pick N employees from the picker dialog and attach them at once."""

    employee_ids: list[uuid.UUID] = Field(min_length=1)


class CandidatePoolItem(BaseModel):
    """HRP-95 / HRP-173: a single row inside the Add candidate picker dialog.

    `status` is "matched" when the computed `match_score` clears the card's
    requirements (100% of required competences at/above threshold, or full
    coverage of `min_experience_years`), "not_matched" otherwise. HRP-214
    adds a third value — "appointed" — surfaced only in Change mode for
    already-attached appointed candidates so the picker can lock the row.
    `basis`
    tells the UI whether the score came from assessment results, work
    experience, or there was nothing to match against.

    HRP-173 adds the per-axis breakdown so the dialog can colour-code the
    Competencies and Experience cells independently:

    * `comp_match` / `comp_qualifies` — competence average percent and
      whether it clears the card-level Match% threshold.
    * `exp_months` / `exp_qualifies` — total tenure (in months) on
      positions matching the card's Required Specializations and whether
      it clears the `min_experience_years` floor for at least one spec.
    * `has_comp_requirement` / `has_spec_requirement` — copies of the
      card's requirement-block presence so the UI doesn't have to fetch
      the card again to know which rendering rule applies.
    """

    employee_id: uuid.UUID
    name: str
    status: str
    match_score: int
    basis: str
    comp_match: int | None = None
    comp_qualifies: bool = False
    exp_months: int | None = None
    exp_qualifies: bool = False
    has_comp_requirement: bool = False
    has_spec_requirement: bool = False
    # HRP-210: when the employee has no qualifying WorkExperience row
    # but their current Position matches one of the Required
    # Specializations, the UI shows a greyed "has experience" chip
    # (and the drawer surfaces "Current position"). False when the
    # standard WorkExperience match already covered the spec.
    exp_via_current_position: bool = False
    # HRP-258: feeds ``EmployeeSummaryLine`` on the Talent Market
    # picker so each row shows position + non-active status chip
    # next to the name without an extra round-trip per employee.
    position_title: str | None = None
    employee_status: str | None = None


class CandidatePoolList(BaseModel):
    items: list[CandidatePoolItem]


# HRP-172: per-candidate match drawer (Sheet) — one row per Required
# Competence + one row per Required Specialization. `actual_*` fields
# stay None when the employee has nothing matching the requirement.


class CandidateBreakdownCompetenceRow(BaseModel):
    competence_id: uuid.UUID
    competence_title: str
    required_skill_level_id: uuid.UUID | None
    required_skill_level_title: str | None
    card_match_percent: int
    actual_percent: int | None
    qualifies: bool


class CandidateBreakdownSpecRow(BaseModel):
    specialization_id: uuid.UUID
    specialization_title: str
    grade_id: uuid.UUID | None
    grade_title: str | None
    required_years: int | None
    actual_months: int | None
    qualifies: bool
    # HRP-210: True when the row's qualification rests on the
    # employee's current Position (no matching WorkExperience entry,
    # current_position lines up with the spec). The drawer surfaces
    # "Current position" greyed for those rows.
    current_position_match: bool = False


class CandidateBreakdown(BaseModel):
    employee_id: uuid.UUID
    employee_name: str | None
    card_match_percent: int
    competences: list[CandidateBreakdownCompetenceRow]
    specializations: list[CandidateBreakdownSpecRow]


class CandidateRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    # HRP-149: render "Name Last name" on the Candidates block, not the uuid.
    employee_name: str | None = None
    # HRP-149: viewer-scoped flag — the UI links the name only when True.
    # admin / hr / platform_admin → always True; manager → True for own
    # division subtree; employee → True only for their own row. Defaults
    # to True so legacy endpoints (add / appoint) that hand back a single
    # candidate row keep the link behaviour they had before the role gate.
    can_view_profile: bool = True
    # HRP-209: True when this candidate row belongs to the viewer.
    # Drives "it's me" copy, drawer-arrow visibility (Employee can only
    # open the drawer on their own row) and Appoint hiding on the UI.
    is_me: bool = False
    status: str
    match_score: int | None
    # HRP-129: how the score was derived — `competence` (assessment average),
    # `specialization` (presence/tenure of matching positions), or `none`
    # (no Required block on the card or no qualifying assessments).
    basis: str | None = None
    # HRP-173: per-axis match breakdown the card-detail Match cell renders
    # next to each candidate. Mirrors CandidatePoolItem so the same UI
    # colour rules apply whether the row is in the Candidates list or the
    # Add/Change dialog.
    comp_match: int | None = None
    comp_qualifies: bool = False
    exp_months: int | None = None
    exp_qualifies: bool = False
    has_comp_requirement: bool = False
    has_spec_requirement: bool = False
    # HRP-210: mirrors CandidatePoolItem — True when the Experience
    # axis got its green light from the employee's current Position
    # rather than a tenured WorkExperience entry.
    exp_via_current_position: bool = False
    # HRP-258: surfaces the employee's denormalised position + status
    # on the Candidates table so the row can render
    # ``EmployeeSummaryLine`` (position underneath the name + a chip
    # when the employee is not ``active``).
    position_title: str | None = None
    employee_status: str | None = None
    assessment_id: uuid.UUID | None
    pdp_id: uuid.UUID | None
    response_at: datetime | None
    appointed_at: datetime | None
    model_config = {"from_attributes": True}
