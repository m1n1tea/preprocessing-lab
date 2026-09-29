"""Focused guarantees for each clean text transformation."""

from collections import Counter

import pytest

from metallab.preprocessing.stages import (
    ProtectionRegistry,
    clean_controls,
    correct_ocr,
    detect_ocr_suspects,
    expand_abbreviations,
    normalize_dates,
    normalize_unicode,
    normalize_units,
    normalize_whitespace,
    protect_inline_values,
    recognize_number_units,
    repair_hyphenation,
    repeated_furniture,
    serialize_formula,
    serialize_table,
    validate_integrity,
    validate_numeric_values,
)


def test_unicode_nfc_preserves_case_and_symbols() -> None:
    assert normalize_unicode("Fe e\u0301 γ МПа") == "Fe é γ МПа"


def test_control_cleanup_preserves_linebreaks_and_tabs() -> None:
    assert clean_controls("A\x00\tB\nC\x1f") == "A\tB\nC"
    assert normalize_whitespace(clean_controls("A\rB")) == "A\nB"


def test_whitespace_normalization_preserves_meaningful_lines() -> None:
    assert normalize_whitespace(" A  \tB \n C\n\n\nD ") == "A B\nC\n\nD"


def test_repeated_furniture_requires_same_text_on_distinct_pages() -> None:
    pages = [
        {"page_idx": 0, "blocks": [{"type": "header", "content": "Review No. 4"}]},
        {"page_idx": 1, "blocks": [{"type": "header", "content": "Review No.4"}]},
        {"page_idx": 2, "blocks": [{"type": "header", "content": "138 Reference title"}]},
    ]
    assert repeated_furniture(pages) == {(0, 0), (1, 0)}


def test_pdf_line_break_hyphenation_is_conservative() -> None:
    assert repair_hyphenation("контроли-\nруемой") == "контролируемой"
    assert repair_hyphenation("произво- дительность") == "производительность"
    assert repair_hyphenation("C-Mn and Nb-\nV") == "C-Mn and Nb-\nV"
    assert repair_hyphenation("non-recrystallization") == "non-recrystallization"
    assert repair_hyphenation("non-\nrecrystallization") == "non-\nrecrystallization"
    assert repair_hyphenation("Ni- content") == "Ni- content"


def test_ocr_suspects_are_detection_only() -> None:
    source = "rol1ed steel 8000С Fe3C"
    assert detect_ocr_suspects(source) == ["rol1ed", "8000С", "Fe3C"]
    assert source == "rol1ed steel 8000С Fe3C"


def test_ocr_requires_exact_approved_rule_and_context() -> None:
    rules = [{"source": "rol1ed", "target": "rolled", "context": "steel"}]
    assert correct_ocr("rol1ed steel", rules) == ("rolled steel", [("rol1ed", "rolled")])
    assert correct_ocr("rol1ed iron", rules) == ("rol1ed iron", [])
    assert correct_ocr("Fe3C 0/O 1/l", []) == ("Fe3C 0/O 1/l", [])


def test_inline_protection_preserves_original_units_and_abbreviations() -> None:
    registry = ProtectionRegistry()
    original = "КП with 15   MPa"
    sealed, counts = protect_inline_values(original, registry, {"КП": "controlled rolling"}, 0, 1)
    assert counts == Counter({"abbreviation": 1, "number_unit": 1})
    assert registry.restore(normalize_whitespace(sealed)) == original


def test_formula_protection_restores_exact_latex() -> None:
    registry = ProtectionRegistry()
    raw = r"\alpha_0 = 15\,\mathrm{MPa}"
    marker = registry.protect("formula", serialize_formula(raw, []), 2, 3)
    restored = registry.restore("text " + marker)
    assert raw in restored
    validate_integrity(restored, registry)


def test_table_protection_restores_exact_html() -> None:
    registry = ProtectionRegistry()
    html = "<table><tr><td>15 MPa</td></tr></table>"
    marker = registry.protect("table", serialize_table(html, ["Yield stress"]), 0, 1)
    assert registry.restore(marker).endswith(html)
    with pytest.raises(ValueError, match="missing or duplicated"):
        registry.restore(marker + marker)


def test_number_unit_recognition_and_original_preservation() -> None:
    source = "15 MPa, 18,7 мм, 20 °C and Fe3C"
    assert recognize_number_units(source) == ["15 MPa", "18,7 мм", "20 °C"]
    result, changes = normalize_units(source)
    assert "15 MPa [SI: 15000000 Pa]" in result
    assert "18,7 мм [SI: 0.0187 m]" in result
    assert "20 °C" in result
    assert "Fe3C" in result
    assert recognize_number_units("0.06 wt.% C") == ["0.06 wt.%"]
    assert len(changes) == 2
    ranged, _ = normalize_units("16–20 мм, 1250°C, 20 min")
    assert "16–20 мм [SI: 0.016–0.02 m]" in ranged
    assert "1250°C" in ranged
    assert "20 min [SI: 1200 s]" in ranged


def test_date_normalization_keeps_original_and_rejects_invalid() -> None:
    result, changes = normalize_dates("31.12.1981 and 31.02.1981")
    assert result == "31.12.1981 [ISO: 1981-12-31] and 31.02.1981"
    assert len(changes) == 1


def test_abbreviation_dictionary_expands_once_and_preserves_original() -> None:
    seen: set[str] = set()
    result, changes = expand_abbreviations(
        "КП+УО, затем КП", {"КП": "контролируемая прокатка", "УО": "ускоренное охлаждение"}, seen
    )
    assert result == "КП [контролируемая прокатка]+УО [ускоренное охлаждение], затем КП"
    assert len(changes) == 2
    assert expand_abbreviations("КП", {"КП": "контролируемая прокатка"}, seen) == ("КП", [])


def test_final_integrity_rejects_unrestored_marker_and_empty_text() -> None:
    registry = ProtectionRegistry()
    marker = registry.protect("formula", "x=1", 0, 0)
    with pytest.raises(ValueError, match="Unrestored"):
        validate_integrity(marker, registry)
    with pytest.raises(ValueError, match="no text"):
        validate_integrity("", ProtectionRegistry())


def test_integrity_rejects_lost_numeric_value() -> None:
    with pytest.raises(ValueError, match="numeric tokens lost"):
        validate_numeric_values("Fe3C at 20 mm", "FeC at 20 mm")


def test_normalization_never_deletes_numeric_tokens() -> None:
    source = "100 МПа and 20 mm"
    result, _ = normalize_units(source)
    assert not Counter(["100", "20"]) - Counter(__import__("re").findall(r"\d+", result))
