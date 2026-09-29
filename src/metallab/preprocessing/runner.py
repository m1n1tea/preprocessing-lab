"""Build the clean GraphRAG corpus from validated MinerU structured blocks."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from metallab.config import load_experiment
from metallab.extraction import validate_extraction
from metallab.preprocessing.stages import (
    Audit,
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
    repair_hyphenation_with_changes,
    repeated_furniture,
    serialize_formula,
    serialize_table,
    validate_integrity,
    validate_numeric_values,
)

logger = logging.getLogger(__name__)


class CleanCorpusError(RuntimeError):
    """Structured extraction or preprocessing failed validation."""


@dataclass(frozen=True)
class CleanDocument:
    source_id: str
    input_path: Path
    report_path: Path
    audit_path: Path
    characters: int
    counts: dict[str, int]


@dataclass(frozen=True)
class CleanCorpusSummary:
    documents: tuple[CleanDocument, ...]

    @property
    def character_count(self) -> int:
        return sum(document.characters for document in self.documents)


def _captions(block: dict[str, Any]) -> list[str]:
    captions = block.get("captions") or []
    return [
        entry["content"] for entry in captions if isinstance(entry, dict) and entry.get("content")
    ]


def _apply_simple(
    text: str, stage: str, operation: Any, audit: Audit, page: int, block: int
) -> str:
    result = operation(text)
    audit.record(stage, text, result, page, block)
    return result


def _process_document(
    source_id: str, structured: dict[str, Any], policy: dict[str, Any]
) -> tuple[str, dict[str, Any], Audit]:
    pages = structured.get("pages")
    if not isinstance(pages, list) or not pages:
        raise CleanCorpusError(f"{source_id}: structured output has no pages")
    furniture = repeated_furniture(pages, int(policy["repeated_furniture_min_pages"]))
    audit = Audit()
    registry = ProtectionRegistry()
    pieces: list[str] = []
    originals: list[str] = []
    seen_abbreviations: set[str] = set()
    block_count = 0
    for page in pages:
        page_index = page["page_idx"]
        for block_index, block in enumerate(page["blocks"]):
            block_count += 1
            kind = block.get("type", "")
            raw = block.get("content") or ""
            if not isinstance(raw, str):
                raise CleanCorpusError(f"{source_id}: non-text block content at page {page_index}")
            if (page_index, block_index) in furniture:
                audit.record("repeated_header_footer_removed", raw, "", page_index, block_index)
                continue
            if kind == "page_number":
                audit.record("page_number_removed", raw, "", page_index, block_index)
                continue
            captions = _captions(block)
            if kind in {"equation", "table"}:
                # All raw technical content is sealed before prose transformations.
                content = (
                    serialize_formula(raw, captions)
                    if kind == "equation"
                    else serialize_table(raw, captions)
                )
                marker = registry.protect(
                    "formula" if kind == "equation" else "table", content, page_index, block_index
                )
                pieces.append(marker)
                originals.append(raw)
                audit.counts["formula_protected" if kind == "equation" else "table_protected"] += 1
                continue
            if kind in {"image", "chart"} and not raw and captions:
                raw = "Figure: " + " ".join(captions)
            if not raw.strip():
                continue
            originals.append(raw)
            inline_registry = ProtectionRegistry()
            text, protected_counts = protect_inline_values(
                raw, inline_registry, policy["abbreviations"], page_index, block_index
            )
            for protected_kind, count in protected_counts.items():
                audit.counts[f"{protected_kind}_protected"] += count
            text = _apply_simple(
                text, "unicode_nfc", normalize_unicode, audit, page_index, block_index
            )
            text = _apply_simple(
                text, "control_cleanup", clean_controls, audit, page_index, block_index
            )
            text = _apply_simple(
                text,
                "whitespace_normalization",
                normalize_whitespace,
                audit,
                page_index,
                block_index,
            )
            text, hyphen_changes = repair_hyphenation_with_changes(text)
            for before, after in hyphen_changes:
                audit.record("hyphenation_repair", before, after, page_index, block_index)
            text = inline_registry.restore(text)
            for protected_kind, count in protected_counts.items():
                audit.counts[f"{protected_kind}_restored"] += count
            suspects = detect_ocr_suspects(text)
            for suspect in suspects:
                audit.suspects.append(
                    {"page": page_index + 1, "block": block_index, "text": suspect}
                )
            audit.counts["ocr_suspects"] += len(suspects)
            corrected, corrections = correct_ocr(text, policy["ocr_corrections"])
            for before, after in corrections:
                audit.record("ocr_correction", before, after, page_index, block_index)
            text = corrected
            recognized = recognize_number_units(text)
            audit.counts["number_units_recognized"] += len(recognized)
            text, unit_changes = normalize_units(text)
            for before, after in unit_changes:
                audit.record("unit_normalization", before, after, page_index, block_index)
            text, date_changes = normalize_dates(text)
            for before, after in date_changes:
                audit.record("date_normalization", before, after, page_index, block_index)
            text, abbreviation_changes = expand_abbreviations(
                text, policy["abbreviations"], seen_abbreviations
            )
            for before, after in abbreviation_changes:
                audit.record("abbreviation_expansion", before, after, page_index, block_index)
            if text:
                validate_numeric_values(raw, text)
                pieces.append(text)
    text = registry.restore("\n\n".join(pieces).strip() + "\n")
    validate_integrity(text, registry)
    # Every source digit sequence in retained blocks must still appear. Added SI/ISO
    # annotations may add digits, but cannot hide loss of a source value.
    source_numbers = Counter(
        number for raw in originals for number in re.findall(r"\d+(?:[.,]\d+)?", raw)
    )
    result_numbers = Counter(re.findall(r"\d+(?:[.,]\d+)?", text))
    missing = source_numbers - result_numbers
    if missing:
        raise CleanCorpusError(f"{source_id}: source numeric tokens lost: {missing.most_common(5)}")
    audit.counts["formula_restored"] = audit.counts["formula_protected"]
    audit.counts["table_restored"] = audit.counts["table_protected"]
    audit.counts["integrity_validated"] = 1
    report = {
        "source_id": source_id,
        "source_format": "MinerU structured_content.json",
        "page_count": len(pages),
        "block_count": block_count,
        "output_characters": len(text),
        "counts": dict(sorted(audit.counts.items())),
        "ocr_suspects": audit.suspects,
        "protected_structures": [
            {"kind": item.kind, "page": item.page + 1, "block": item.block}
            for item in registry.items.values()
        ],
        "integrity": "passed",
    }
    return text, report, audit


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_clean_corpus(
    config_path: Path = Path("configs/experiment.yaml"),
    mineru_config_path: Path = Path("configs/mineru.yaml"),
    preprocessing_config_path: Path = Path("configs/preprocessing.yaml"),
) -> CleanCorpusSummary:
    """Validate both extractions, preprocess both, then publish corpus and reports."""
    validate_extraction(config_path, mineru_config_path)
    experiment = load_experiment(config_path)
    root = config_path.resolve().parent.parent
    with preprocessing_config_path.open(encoding="utf-8") as stream:
        policy = yaml.safe_load(stream)
    if (
        not isinstance(policy, dict)
        or not isinstance(policy.get("abbreviations"), dict)
        or not isinstance(policy.get("ocr_corrections"), list)
    ):
        raise CleanCorpusError("Preprocessing config needs abbreviations and ocr_corrections")
    if (
        not isinstance(policy.get("repeated_furniture_min_pages"), int)
        or policy["repeated_furniture_min_pages"] < 2
    ):
        raise CleanCorpusError("repeated_furniture_min_pages must be at least 2")
    if any(
        not isinstance(short, str) or not short or not isinstance(full, str) or not full
        for short, full in policy["abbreviations"].items()
    ):
        raise CleanCorpusError("Each abbreviation needs non-empty text and expansion")
    if any(
        not isinstance(rule, dict)
        or any(
            not isinstance(rule.get(field), str) or not rule[field]
            for field in ("source", "target", "context")
        )
        for rule in policy["ocr_corrections"]
    ):
        raise CleanCorpusError("Each OCR rule needs source, target and literal context")
    pending: list[tuple[str, str, dict[str, Any], Audit]] = []
    for source in experiment.sources:
        path = root / experiment.paths.mineru / source.id / "structured_content.json"
        structured = json.loads(path.read_text(encoding="utf-8"))
        text, report, audit = _process_document(source.id, structured, policy)
        pending.append((source.id, text, report, audit))
    output_root = root / experiment.paths.clean
    documents: list[CleanDocument] = []
    for source_id, content, report, audit in pending:
        input_path = output_root / "input" / f"{source_id}.txt"
        report_path = output_root / "reports" / f"{source_id}.json"
        audit_path = output_root / "audit" / f"{source_id}.jsonl"
        _write_atomic(input_path, content)
        _write_atomic(
            report_path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        _write_atomic(
            audit_path,
            "".join(
                json.dumps(asdict(change), ensure_ascii=False, sort_keys=True) + "\n"
                for change in audit.changes
            ),
        )
        for change in audit.changes:
            logger.debug(
                "%s page %s block %s %s: %r -> %r",
                source_id,
                change.page + 1,
                change.block,
                change.stage,
                change.before,
                change.after,
            )
        logger.info(
            "Clean document %s: %s characters, transformations=%s -> %s",
            source_id,
            len(content),
            dict(audit.counts),
            input_path,
        )
        documents.append(
            CleanDocument(
                source_id, input_path, report_path, audit_path, len(content), dict(audit.counts)
            )
        )
    summary = CleanCorpusSummary(tuple(documents))
    logger.info(
        "Clean corpus complete: %s documents, %s characters",
        len(documents),
        summary.character_count,
    )
    return summary
