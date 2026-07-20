"""Unit tests for app.core.pii_filter (multi-locale)."""

from app.core.pii_filter import redact_pii

# ---------------------------------------------------------------------------
# Universal patterns
# ---------------------------------------------------------------------------


def test_redact_pii_credit_card_with_spaces():
    text = "Card on file: 4111 1111 1111 1111 expires 12/29."
    out = redact_pii(text)
    assert "4111 1111 1111 1111" not in out
    assert "[REDACTED:credit_card]" in out


def test_redact_pii_credit_card_compact():
    out = redact_pii("Pay 4111111111111111 by Friday.")
    assert "4111111111111111" not in out
    assert "[REDACTED:credit_card]" in out


def test_redact_pii_credit_card_with_dashes():
    out = redact_pii("Use card 4111-1111-1111-1111 for verification.")
    assert "[REDACTED:credit_card]" in out


def test_redact_pii_iban_german():
    text = "Wire the bonus to DE89370400440532013000."
    out = redact_pii(text)
    assert "DE89370400440532013000" not in out
    assert "[REDACTED:iban]" in out


def test_redact_pii_iban_uk():
    out = redact_pii("Account: GB82WEST12345698765432.")
    assert "GB82WEST12345698765432" not in out
    assert "[REDACTED:iban]" in out


# ---------------------------------------------------------------------------
# US — Social Security Number
# ---------------------------------------------------------------------------


def test_redact_pii_us_ssn():
    text = "Candidate SSN: 123-45-6789."
    out = redact_pii(text)
    assert "123-45-6789" not in out
    assert "[REDACTED:ssn]" in out


# ---------------------------------------------------------------------------
# EU — UK NIN, Spanish DNI, Italian Codice Fiscale
# ---------------------------------------------------------------------------


def test_redact_pii_uk_nin_compact():
    out = redact_pii("National Insurance Number: AB123456C.")
    assert "AB123456C" not in out
    assert "[REDACTED:nin]" in out


def test_redact_pii_uk_nin_spaced():
    out = redact_pii("NIN AB 12 34 56 C on the right-to-work form.")
    assert "[REDACTED:nin]" in out


def test_redact_pii_es_dni():
    out = redact_pii("DNI 12345678Z verified on 2024-01-12.")
    assert "12345678Z" not in out
    assert "[REDACTED:dni]" in out


def test_redact_pii_it_codice_fiscale():
    out = redact_pii("Codice Fiscale RSSMRA85M01H501Z is on file.")
    assert "RSSMRA85M01H501Z" not in out
    assert "[REDACTED:codice_fiscale]" in out


# ---------------------------------------------------------------------------
# RU — passport, INN, SNILS
# ---------------------------------------------------------------------------


def test_redact_pii_passport_with_space():
    text = "Passport 4514 123456 issued 01.01.2010."
    out = redact_pii(text)
    assert "4514 123456" not in out
    assert "[REDACTED:passport]" in out


def test_redact_pii_passport_no_space_is_treated_as_inn():
    """A 10-digit run with no space is claimed by the INN regex.

    This is the documented trade-off in pii_filter.py: keeping the
    space-less passport rule would shadow legal-entity INN values, so we
    accept the false-negative and rely on context.
    """

    text = "Series and number 4514123456"
    out = redact_pii(text)
    assert "4514123456" not in out
    assert "[REDACTED:inn]" in out


def test_redact_pii_inn_individual():
    text = "Tax ID 123456789012 listed in the form."
    out = redact_pii(text)
    assert "123456789012" not in out
    assert "[REDACTED:inn]" in out


def test_redact_pii_inn_legal_entity():
    text = "Counterparty tax ID 7707083893."
    out = redact_pii(text)
    assert "7707083893" not in out
    assert "[REDACTED:inn]" in out


def test_redact_pii_snils_space():
    text = "Social insurance number 123-456-789 12 on file."
    out = redact_pii(text)
    assert "123-456-789 12" not in out
    assert "[REDACTED:snils]" in out


def test_redact_pii_snils_dash():
    out = redact_pii("Social insurance number 123-456-789-12.")
    assert "[REDACTED:snils]" in out


# ---------------------------------------------------------------------------
# Modes, empty input, false-positive safety
# ---------------------------------------------------------------------------


def test_redact_pii_mask_mode():
    out = redact_pii("Tax ID 123456789012", mode="mask")
    assert "***" in out
    assert "REDACTED" not in out


def test_redact_pii_empty_string_safe():
    assert redact_pii("") == ""


def test_redact_pii_none_safe():
    assert redact_pii(None) == ""


def test_redact_pii_preserves_short_numbers():
    text = "Worked for 5 years, shipped 200 projects and earned 1500000 in revenue."
    out = redact_pii(text)
    # Short numbers (≤9 digits) must not be touched.
    assert "5 years" in out
    assert "200" in out
    assert "1500000" in out


def test_redact_pii_handles_multiple_in_one_string():
    text = (
        "Passport 4514 123456, tax ID 7707083893, "
        "social insurance 123-456-789-12."
    )
    out = redact_pii(text)
    assert "[REDACTED:passport]" in out
    assert "[REDACTED:inn]" in out
    assert "[REDACTED:snils]" in out


def test_redact_pii_handles_mixed_locales_in_one_string():
    text = (
        "Cross-border file: card 4111 1111 1111 1111, "
        "IBAN DE89370400440532013000, SSN 123-45-6789, "
        "NIN AB123456C, DNI 12345678Z."
    )
    out = redact_pii(text)
    assert "[REDACTED:credit_card]" in out
    assert "[REDACTED:iban]" in out
    assert "[REDACTED:ssn]" in out
    assert "[REDACTED:nin]" in out
    assert "[REDACTED:dni]" in out
    # Raw values are gone.
    assert "4111 1111 1111 1111" not in out
    assert "DE89370400440532013000" not in out
    assert "123-45-6789" not in out
    assert "AB123456C" not in out
    assert "12345678Z" not in out
