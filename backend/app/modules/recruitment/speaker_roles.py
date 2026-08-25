"""Recover who spoke when a provider gives no diarization (HRP-646).

Whisper returns one voice for the whole recording: every segment lands as
``speaker_0``, and the analysis then scores competences without knowing
which words are the candidate's and which are the interviewer's own
question. Providers that diarize natively (Deepgram, AssemblyAI,
SpeechKit) make this pass unnecessary — it runs only when the transcript
came back single-voiced.

This is role attribution, not acoustic diarization: no audio is involved,
the model reads the turns and decides which ones ask and which ones
answer. For the one-on-one interview this module transcribes that is the
whole distinction; a panel of three will collapse into two roles.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from pydantic import BaseModel, Field

from app.core.pii_filter import redact_pii
from app.modules.ai.prompt_sanitizer import sanitize_inline
from app.modules.recruitment.transcription_service import TranscriptSegment

logger = logging.getLogger(__name__)

# A cheap pass over the turns, not an analysis: the output is a list of
# integers, and the transcript itself dominates the token count.
_MAX_TOKENS = 4000

_SYSTEM_PROMPT = (
    "You label the turns of a job interview transcript. The recording has "
    "no speaker separation, so you decide which numbered turns were spoken "
    "by the interviewer (the person asking questions, describing the role, "
    "steering the conversation) and which by the candidate (the person "
    "answering, describing their own experience). Return only the numbers "
    "of the interviewer's turns. Judge by content, not by length: a short "
    "acknowledgement inside a long answer still belongs to whoever was "
    "answering."
)


class _InterviewerTurns(BaseModel):
    interviewer_turns: list[int] = Field(default_factory=list)


def label_speakers_sync(
    db,
    tenant_id: uuid.UUID,
    segments: list[TranscriptSegment],
    *,
    language: str | None = None,
) -> list[TranscriptSegment] | None:
    """Split single-voiced segments into interviewer and candidate.

    Returns a new segment list, or ``None`` when the pass did not produce
    a usable answer — the caller keeps the single-speaker transcript, which
    is what it had before. A failure here must never cost the interview its
    transcript.
    """

    if not segments:
        return None

    from app.modules.ai.llm_client import generate_json
    from app.modules.ai.model_catalog_service import resolve_dispatch_model_sync
    from app.modules.ai.providers import resolve_generation_target_sync

    # Redacted before it travels: the stored transcript is redacted too, so
    # the model sees exactly what the analysis will later read.
    turns = "\n".join(
        f"{index}: {sanitize_inline(redact_pii(seg.text))}"
        for index, seg in enumerate(segments)
        if seg.text
    )
    prompt = (
        f"Interview language: {language or 'unknown'}\n"
        f"Numbered turns:\n{turns}\n\n"
        "Return the numbers of the turns spoken by the interviewer."
    )

    try:
        creds = resolve_generation_target_sync(db, tenant_id, None)
        answer = asyncio.run(
            generate_json(
                prompt=prompt,
                system=_SYSTEM_PROMPT,
                schema=_InterviewerTurns,
                temperature=0.0,
                max_tokens=_MAX_TOKENS,
                credentials=creds,
                model=resolve_dispatch_model_sync(db, creds.model),
            )
        )
    except Exception:  # noqa: BLE001 - a failed role pass must not fail the transcript
        logger.exception("Speaker role labelling failed; keeping one speaker")
        return None

    if not isinstance(answer, _InterviewerTurns):
        return None

    interviewer = {i for i in answer.interviewer_turns if 0 <= i < len(segments)}
    # All turns or none means the model did not actually separate anyone —
    # a single label is what we already have, so nothing is gained by
    # rewriting the transcript with it.
    if not interviewer or len(interviewer) == len(segments):
        logger.info(
            "Speaker role labelling returned %s of %s turns as interviewer — "
            "keeping one speaker",
            len(interviewer),
            len(segments),
        )
        return None

    return [
        TranscriptSegment(
            # speaker_0 is the interviewer, matching the labels the manual
            # "Interviewer:"/"Candidate:" transcript parser assigns.
            speaker="speaker_0" if index in interviewer else "speaker_1",
            start=seg.start,
            end=seg.end,
            text=seg.text,
            confidence=seg.confidence,
        )
        for index, seg in enumerate(segments)
    ]


__all__ = ["label_speakers_sync"]
