"""HRP-282: title/description length caps for every dictionary type.

The DB columns stay at 255/500 — the validators sit on
``DictionaryItemCreate`` / ``DictionaryItemUpdate`` and apply to all six
dictionaries (Grades / Specializations / Competence Types / Roles /
Goals / Projects) routed through ``app/modules/dictionary``.
"""

import pytest
from app.modules.dictionary.schemas import (
    DESCRIPTION_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    DictionaryItemCreate,
    DictionaryItemUpdate,
)
from pydantic import ValidationError


class TestHRP282Limits:
    def test_constants(self):
        assert TITLE_MAX_LENGTH == 100
        assert DESCRIPTION_MAX_LENGTH == 250

    def test_create_accepts_title_at_limit(self):
        DictionaryItemCreate(title="x" * TITLE_MAX_LENGTH)

    def test_create_rejects_title_over_limit(self):
        with pytest.raises(ValidationError):
            DictionaryItemCreate(title="x" * (TITLE_MAX_LENGTH + 1))

    def test_create_accepts_description_at_limit(self):
        DictionaryItemCreate(
            title="ok", description="d" * DESCRIPTION_MAX_LENGTH
        )

    def test_create_rejects_description_over_limit(self):
        with pytest.raises(ValidationError):
            DictionaryItemCreate(
                title="ok", description="d" * (DESCRIPTION_MAX_LENGTH + 1)
            )

    def test_update_rejects_title_over_limit(self):
        with pytest.raises(ValidationError):
            DictionaryItemUpdate(title="x" * (TITLE_MAX_LENGTH + 1))

    def test_update_rejects_description_over_limit(self):
        with pytest.raises(ValidationError):
            DictionaryItemUpdate(description="d" * (DESCRIPTION_MAX_LENGTH + 1))

    def test_update_allows_partial_payload(self):
        # Optional fields stay optional — only the lengths are enforced.
        DictionaryItemUpdate(is_active=False)
