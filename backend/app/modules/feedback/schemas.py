"""Request schema for in-product feedback (HRP-586, HRP-587)."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

# "platform" — the "?" widget in the app header (HRP-586);
# "demo" — the delayed popup shown inside a demo sandbox (HRP-587).
FeedbackSource = Literal["platform", "demo"]


class FeedbackCreate(BaseModel):
    """One feedback submission. Every field is optional on its own — the
    router rejects a submission that carries neither a rating nor text."""

    rating: Literal["up", "down"] | None = None
    message: str | None = Field(default=None, max_length=2000)
    # Demo popup only: "was everything clear?" (HRP-587).
    clarity: Literal["yes", "no"] | None = None
    # Demo popup only: optional address for a follow-up from sales.
    contact_email: EmailStr | None = None
    source: FeedbackSource = "platform"
