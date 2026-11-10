"""Request schema for in-product feedback (HRP-586, HRP-587)."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

# "platform" — the "?" widget in the app header (HRP-586);
# "demo" — the delayed popup shown inside a demo sandbox (HRP-587).
FeedbackSource = Literal["platform", "demo"]

# Demo popup only (HRP-1158): what the visitor had just done when the card
# asked. The five value moments, plus "timer" for the card shown to those
# who only browsed.
FeedbackContext = Literal[
    "pdp_created",
    "pdp_from_assessment",
    "assessment_created",
    "decomposition_applied",
    "hire_need_created",
    "timer",
]


class FeedbackCreate(BaseModel):
    """One feedback submission. Every field is optional on its own — the
    service rejects a submission with no rating, text, clarity answer,
    context answer, contact email or phone."""

    rating: Literal["up", "down"] | None = None
    message: str | None = Field(default=None, max_length=2000)
    # Demo popup only: "was everything clear?" (HRP-587).
    clarity: Literal["yes", "no"] | None = None
    # Demo popup only: optional address for a follow-up from sales.
    contact_email: EmailStr | None = None
    # Demo popup only: who to ask for, and a phone on sites that offer
    # the field (NEXT_PUBLIC_DEMO_CONTACT_PHONE).
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=40)
    source: FeedbackSource = "platform"
    context: FeedbackContext | None = None
    # The object the card asked about ("Q3 plan for Will Gapp").
    context_title: str | None = Field(default=None, max_length=200)
    # The card's one-click answer to its question about that object.
    answer: Literal["yes", "partly", "no"] | None = None
