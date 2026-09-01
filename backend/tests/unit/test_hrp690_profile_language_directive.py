"""HRP-690: vacancy profile / individual questions honor the content language.

The tenant's AI content language used to reach the prompt only as a bare
ISO code ("Respond in ru language") buried under kilobytes of English JSON
exemplars — the model answered in English anyway. The fix injects the
named-language directive (HRP-541 pattern) into the system prompt and the
tail of the user prompt.
"""

from app.modules.ai_settings.service import language_directive
from app.modules.recruitment import ai_service


def test_language_directive_names_the_language() -> None:
    assert "Generate ALL content in Russian" in language_directive("ru")
    assert "Generate ALL content in German" in language_directive("de")
    # Unknown / missing codes fall back to English.
    assert "Generate ALL content in English" in language_directive("xx")
    assert "Generate ALL content in English" in language_directive(None)


async def test_generate_vacancy_profile_carries_directive(monkeypatch) -> None:
    captured: dict = {}

    async def fake_generate_json(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["system"] = kwargs["system"]
        return {"competences": []}

    monkeypatch.setattr(ai_service, "generate_json", fake_generate_json)

    await ai_service.generate_vacancy_profile(
        {"title": "Dev", "vacancy_id": "v1", "language": "ru"}
    )

    assert "Generate ALL content in Russian" in captured["system"]
    assert "Generate ALL content in Russian" in captured["prompt"]
    assert "Respond in ru language" not in captured["prompt"]


async def test_generate_individual_questions_carries_directive(monkeypatch) -> None:
    captured: dict = {}

    async def fake_generate_json(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["system"] = kwargs["system"]
        return []

    monkeypatch.setattr(ai_service, "generate_json", fake_generate_json)

    await ai_service.generate_individual_questions(
        {"first_name": "A"}, {"competences": []}, "Dev", language="ru"
    )

    assert "Generate ALL content in Russian" in captured["system"]
    assert "Generate ALL content in Russian" in captured["prompt"]
    assert "Respond in ru language" not in captured["prompt"]
