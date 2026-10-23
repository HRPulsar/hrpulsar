"""HRP-1085: a ready-made transcript splits into segments by its labels.

``_parse_speaker_segments`` is the one parser behind pasted, uploaded and
edited text transcripts. Role words split as before (now in en/de/ru); a
file labelled as a whole by other labels - names - splits too, those
speakers numbered by first appearance.
"""

from __future__ import annotations

import pytest
from app.modules.recruitment.interview_service import _parse_speaker_segments


def _shape(text: str) -> list[tuple[str, str]]:
    return [(s["speaker"], s["text"]) for s in _parse_speaker_segments(text)]


@pytest.mark.parametrize(
    "text",
    [
        "Interviewer: Tell me about yourself.\nCandidate: I build backends.",
        "Interviewer:in: Tell me about yourself.\nBewerber:in: I build backends.",
        "Recruiter: Tell me about yourself.\nApplicant: I build backends.",
    ],
)
def test_role_words_map_to_the_roles(text: str) -> None:
    assert _shape(text) == [
        ("speaker_0", "Tell me about yourself."),
        ("speaker_1", "I build backends."),
    ]


def test_role_words_in_german() -> None:
    # The ru role words are pinned in tests/unit/ee (no Cyrillic in public).
    assert [s for s, _ in _shape("Interviewerin: Bitte.\nBewerberin: Gern.")] == [
        "speaker_0",
        "speaker_1",
    ]


def test_names_split_a_labelled_file_in_order_of_appearance() -> None:
    text = (
        "Anna Petrova: Tell me about yourself.\n"
        "Ivan Sidorov: I build backends,\n"
        "mostly in Python.\n"
        "Anna Petrova: Why are you leaving?\n"
        "\n"
        "Ivan Sidorov: To grow."
    )
    assert _shape(text) == [
        ("speaker_0", "Tell me about yourself."),
        # An unlabelled line joins the segment before it.
        ("speaker_1", "I build backends, mostly in Python."),
        ("speaker_0", "Why are you leaving?"),
        ("speaker_1", "To grow."),
    ]


def test_names_next_to_role_words_take_the_next_free_speakers() -> None:
    assert [s for s, _ in _shape("Interviewer: Hi.\nIvan: Hello.\nOlga: Hi.")] == [
        "speaker_0",
        "speaker_2",
        "speaker_3",
    ]


def test_wrapped_pdf_lines_do_not_outvote_the_labels() -> None:
    text = (
        "Anna: This is a long question that\n"
        "wraps over several lines of the pdf\n"
        "before it ends.\n"
        "Boris: And an answer that also\n"
        "wraps."
    )
    assert [s for s, _ in _shape(text)] == ["speaker_0", "speaker_1"]


def test_a_narrative_with_the_odd_label_stays_in_one_piece() -> None:
    text = (
        "The candidate joined the call late.\n"
        "Note: the camera was off.\n"
        "We talked about the role.\n"
        "Summary: a good fit.\n"
        "Next steps were agreed.\n"
        "The call ended on time."
    )
    assert len(_shape(text)) == 1


def test_one_label_alone_does_not_make_a_labelled_file() -> None:
    assert len(_shape("Anna: Hello.\nAnna: Again.")) == 1


@pytest.mark.parametrize(
    "line",
    [
        "However, he said: no.",  # a clause, not a label
        "It was over.: anyway",  # the label ends a sentence
        "One two three four five: too many words.",
        "https://example.com/path",  # a link
        "12: a number is not a speaker",
        "We start at 10:30 sharp.",  # a clock, not a speaker "We start at 10"
    ],
)
def test_lines_that_are_not_labels(line: str) -> None:
    text = f"Anna: Hi.\nBoris: Hello.\n{line}"
    # The line joins Boris instead of opening a segment of its own.
    assert len(_shape(text)) == 2


def test_a_leading_timecode_is_not_read_as_a_label() -> None:
    text = "[00:00:05] Interviewer: Hi.\n00:00:09 Candidate: Hello."
    assert _shape(text) == [("speaker_0", "Hi."), ("speaker_1", "Hello.")]


def test_a_numbered_speaker_is_still_a_label() -> None:
    assert [s for s, _ in _shape("Speaker 1: Hi.\nSpeaker 2: Hello.")] == [
        "speaker_0",
        "speaker_1",
    ]


def test_role_words_come_from_the_catalogs() -> None:
    """The word lists live in ``recruitment.transcript_labels`` of each
    language's catalog, not in the parser (ru ships with ee only)."""
    from app.core.i18n import catalog_list

    assert "interviewer" in catalog_list(
        "recruitment.transcript_labels.interviewer", "en"
    )
    assert "bewerber" in catalog_list("recruitment.transcript_labels.candidate", "de")
    assert catalog_list("recruitment.transcript_labels.candidate", "xx") == []
    # A plain message key is not a list.
    assert catalog_list("errors.not_found", "en") == []


def test_ru_role_words_are_empty_without_ee(monkeypatch) -> None:
    """A community build has no ``ee`` package: the ru list resolves to an
    empty one instead of an error, and the parser still splits by en/de
    role words."""
    import sys

    from app.core import i18n
    from app.core.i18n import catalog_list
    from app.modules.recruitment import interview_service

    monkeypatch.setitem(sys.modules, "ee.i18n_catalogs", None)
    i18n._load_catalog.cache_clear()
    interview_service._role_labels.cache_clear()
    try:
        assert catalog_list("recruitment.transcript_labels.candidate", "ru") == []
        assert _shape("Interviewer: Hi.\nCandidate: Hello.") == [
            ("speaker_0", "Hi."),
            ("speaker_1", "Hello."),
        ]
    finally:
        i18n._load_catalog.cache_clear()
        interview_service._role_labels.cache_clear()
