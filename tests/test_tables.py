"""Camelot table extraction quality and deterministic serialization tests."""

from pathlib import Path

import pandas as pd

from metallab.preprocessing.runner import _policy_defaults, _preprocess_table_content
from metallab.preprocessing.stages import Audit
from metallab.preprocessing.tables import CamelotTableExtractor, validate_camelot_table


def test_camelot_serialization_joins_only_wrapped_numeric_ranges() -> None:
    frame = pd.DataFrame(
        [
            ["Condition", "Reduction"],
            ["70÷7\n5", "81,2"],
        ]
    )
    result = validate_camelot_table(
        frame,
        document="stat3",
        table_id="stat3-T001",
        page=8,
        flavor="lattice",
        accuracy=98.0,
        whitespace=10.0,
    )
    assert result.valid
    assert "70÷75" in result.serialized
    assert "81,2" in result.serialized
    assert result.parsing_accuracy == 98.0


def test_camelot_rejects_low_confidence_tables() -> None:
    result = validate_camelot_table(
        pd.DataFrame([["H1", "H2"], ["x", "1"]]),
        document="stat3",
        table_id="stat3-T001",
        page=8,
        flavor="lattice",
        accuracy=50.0,
        whitespace=10.0,
        minimum_accuracy=70.0,
    )
    assert not result.valid
    assert any("below" in issue for issue in result.issues)


def test_camelot_prefers_acceptable_candidate(monkeypatch) -> None:
    import camelot

    class Candidate:
        def __init__(self, frame: pd.DataFrame, accuracy: float, whitespace: float):
            self.df = frame
            self.parsing_report = {"accuracy": accuracy, "whitespace": whitespace}

    monkeypatch.setattr(
        camelot,
        "read_pdf",
        lambda *args, **kwargs: [
            Candidate(pd.DataFrame([["a", "b"], ["1", "2"]]), 50, 10),
            Candidate(pd.DataFrame([["a", "b"], ["1", "2"]]), 98, 8),
        ],
    )
    result = CamelotTableExtractor().extract(
        Path("unused.pdf"),
        page=8,
        document="stat3",
        table_id="stat3-T001",
        flavor="lattice",
        original="MinerU source",
    )
    assert result.valid
    assert result.parsing_accuracy == 98


def test_table_content_runs_text_cleanup_and_pint_with_column_units() -> None:
    policy = _policy_defaults()
    policy["abbreviations"] = {"КП": "контролируемая прокатка"}
    audit = Audit()
    content = (
        "[TABLE id=stat3-T001 document=stat3 page=8 extractor=Camelot]\n"
        "Row 1: C1=Схема про- катки КП | C2=Параметр | C3=Время | C4=Снижение\n"
        "Row 2: C1=Схема | C2=Температура, 0С | C3=τ, сек | C4=Снижение, %\n"
        "Row 3: C1=Режим | C2=1120÷1150 | C3=50 | C4=78,4\n"
        "[/TABLE]"
    )

    cleaned = _preprocess_table_content(
        content,
        source_id="stat3",
        page=7,
        block=2,
        policy=policy,
        audit=audit,
        seen_abbreviations=set(),
    )

    assert "Схема прокатки" in cleaned
    assert "КП [контролируемая прокатка]" in cleaned
    assert "Температура, 0С [unit: °C]" in cleaned
    assert "1120÷1150 [SI: 1393.15–1423.15 K]" in cleaned
    assert "50 [SI: 50 s]" in cleaned
    assert "78,4 [SI: 0.784]" in cleaned
    assert "K] | C3=50" in cleaned
    assert audit.counts["hyphenation_repair"] == 1
    assert audit.counts["unit_normalization"] == 3
    assert audit.counts["unit_header_normalization"] == 1
    assert len(audit.quantities) == 3
