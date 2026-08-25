"""Unit tests for the LLM speaker-role pass (HRP-646).

The pass runs only where a provider gave no diarization, so its contract
is narrow: either it separates the two voices, or it leaves the transcript
exactly as it found it.
"""

import pytest
from app.modules.ai import llm_client, model_catalog_service, providers
from app.modules.recruitment.speaker_roles import label_speakers_sync
from app.modules.recruitment.transcription_service import TranscriptSegment


def _segments(*texts: str) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            speaker="speaker_0", start=float(i * 5), end=float(i * 5 + 5), text=text
        )
        for i, text in enumerate(texts)
    ]


@pytest.fixture
def llm(monkeypatch):
    """Capture the prompt and answer with a canned turn list."""
    captured: dict = {}

    class _Creds:
        model = "claude-x"

    def _fake_resolve(db, tenant_id, _):
        return _Creds()

    async def _fake_generate(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return captured["answer"]

    monkeypatch.setattr(providers, "resolve_generation_target_sync", _fake_resolve)
    monkeypatch.setattr(
        model_catalog_service, "resolve_dispatch_model_sync", lambda db, m: m
    )
    monkeypatch.setattr(llm_client, "generate_json", _fake_generate)
    return captured


def test_turns_are_split_into_interviewer_and_candidate(llm):
    from app.modules.recruitment.speaker_roles import _InterviewerTurns

    segments = _segments("Tell me about yourself", "I led a team", "And your goals?")
    llm["answer"] = _InterviewerTurns(interviewer_turns=[0, 2])

    result = label_speakers_sync(None, None, segments, language="en")

    assert result is not None
    assert [s.speaker for s in result] == ["speaker_0", "speaker_1", "speaker_0"]
    # Timecodes and text are untouched — only the label changes.
    assert [s.text for s in result] == [s.text for s in segments]
    assert [s.start for s in result] == [s.start for s in segments]
    assert "0: Tell me about yourself" in llm["prompt"]


@pytest.mark.parametrize("turns", [[], [0, 1, 2], [7, 9]])
def test_an_answer_that_separates_nobody_leaves_the_transcript_alone(llm, turns):
    """No turns, every turn, or turns that do not exist: each means the
    model did not actually tell the voices apart."""
    from app.modules.recruitment.speaker_roles import _InterviewerTurns

    llm["answer"] = _InterviewerTurns(interviewer_turns=turns)

    assert label_speakers_sync(None, None, _segments("a", "b", "c")) is None


def test_a_failed_llm_call_never_costs_the_transcript(llm, monkeypatch):
    async def _boom(**kwargs):
        raise RuntimeError("provider is down")

    monkeypatch.setattr(llm_client, "generate_json", _boom)

    assert label_speakers_sync(None, None, _segments("a", "b")) is None


def test_no_segments_means_nothing_to_label(llm):
    assert label_speakers_sync(None, None, []) is None
