"""Build the CLEAN GraphRAG corpus from MinerU structured blocks."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from metallab.config import load_experiment
from metallab.extraction import validate_extraction
from metallab.preprocessing.formulas import formula_metadata
from metallab.preprocessing.stages import (
    Audit,
    ProtectionRegistry,
    clean_controls,
    correct_ocr,
    detect_repeated_furniture,
    expand_abbreviations,
    ftfy_repair,
    inspect_ocr_artifacts,
    is_page_number,
    normalize_dates,
    normalize_unicode,
    normalize_whitespace,
    protect_inline_values,
    repair_hyphenation_with_changes,
    serialize_formula,
    validate_integrity,
    validate_numeric_values,
)
from metallab.preprocessing.tables import CamelotTableExtractor, MinerUTableExtractor
from metallab.preprocessing.units import analyze_quantities

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


def _policy_defaults() -> dict[str, Any]:
    return {
        "unicode": {"normalization": "NFC"},
        "ftfy": {"enabled": True},
        "whitespace": {"enabled": True},
        "headers": {"enabled": True, "candidate_lines": 4, "min_page_fraction": 0.6},
        "page_numbers": {"enabled": True},
        "dehyphenation": {
            "enabled": True,
            "known_terms": [],
            "preserve_prefixes": [],
        },
        "ocr": {"detect": True, "auto_fix_high_confidence_only": True},
        "units": {"enabled": True, "preserve_original": True, "normalize_with_pint": True},
        "tables": {
            "enabled": True,
            "extractor": "mineru",
            "flavor": "lattice",
            "minimum_accuracy": 70.0,
            "maximum_whitespace": 40.0,
            "fallback_to_mineru": True,
            "empty_cell_ratio_limit": 0.5,
            "fragmentation_ratio_limit": 0.35,
        },
        "formulas": {"protect": True, "sympy_validation": False},
        "abbreviations": {},
        "ocr_corrections": [],
    }


def _normalize_policy(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate nested config, retaining compatibility with the previous flat test format."""
    if "preprocessing" not in raw:
        legacy = _policy_defaults()
        legacy["headers"]["min_page_fraction"] = 0.6
        legacy["headers"]["min_repeats"] = raw.get("repeated_furniture_min_pages", 2)
        legacy["abbreviations"] = raw.get("abbreviations", {})
        legacy["ocr_corrections"] = raw.get("ocr_corrections", [])
        if any(
            not isinstance(rule, dict)
            or any(
                not isinstance(rule.get(field), str) or not rule[field]
                for field in ("source", "target", "context")
            )
            for rule in legacy["ocr_corrections"]
        ):
            raise CleanCorpusError("Each OCR correction needs source, target, and literal context")
        return legacy
    section = raw.get("preprocessing")
    if not isinstance(section, dict):
        raise CleanCorpusError("Preprocessing config needs a mapping named 'preprocessing'")
    result = _policy_defaults()
    for key in result:
        if key in {"abbreviations", "ocr_corrections"}:
            continue
        value = section.get(key, {})
        if not isinstance(value, dict):
            raise CleanCorpusError(f"preprocessing.{key} must be a mapping")
        result[key].update(value)
    result["abbreviations"] = section.get("abbreviations", raw.get("abbreviations", {}))
    result["ocr_corrections"] = section.get("ocr_corrections", raw.get("ocr_corrections", []))
    if not isinstance(result["abbreviations"], dict) or not isinstance(
        result["ocr_corrections"], list
    ):
        raise CleanCorpusError("Abbreviations must be a mapping and OCR corrections must be a list")
    if result["unicode"].get("normalization") != "NFC":
        raise CleanCorpusError("Only NFC Unicode normalization is supported")
    headers = result["headers"]
    if not isinstance(headers.get("candidate_lines"), int) or headers["candidate_lines"] < 1:
        raise CleanCorpusError("headers.candidate_lines must be a positive integer")
    if (
        not isinstance(headers.get("min_page_fraction"), (int, float))
        or not 0 < headers["min_page_fraction"] <= 1
    ):
        raise CleanCorpusError("headers.min_page_fraction must be between 0 and 1")
    if "min_repeats" in headers and (
        not isinstance(headers["min_repeats"], int) or headers["min_repeats"] < 2
    ):
        raise CleanCorpusError("headers.min_repeats must be at least two")
    for section_name, key in (
        ("ftfy", "enabled"),
        ("whitespace", "enabled"),
        ("headers", "enabled"),
        ("page_numbers", "enabled"),
        ("dehyphenation", "enabled"),
        ("ocr", "detect"),
        ("units", "enabled"),
        ("tables", "enabled"),
        ("formulas", "protect"),
        ("units", "preserve_original"),
        ("units", "normalize_with_pint"),
        ("ocr", "auto_fix_high_confidence_only"),
        ("tables", "fallback_to_mineru"),
        ("formulas", "sympy_validation"),
    ):
        if not isinstance(result[section_name].get(key), bool):
            raise CleanCorpusError(f"preprocessing.{section_name}.{key} must be boolean")
    if not result["units"]["preserve_original"]:
        raise CleanCorpusError("preprocessing.units.preserve_original must remain true")
    if not result["formulas"]["protect"]:
        raise CleanCorpusError("preprocessing.formulas.protect must remain true")
    if result["tables"].get("extractor") not in {"camelot", "mineru"}:
        raise CleanCorpusError("preprocessing.tables.extractor must be camelot or mineru")
    if result["tables"].get("flavor") not in {"lattice", "stream"}:
        raise CleanCorpusError("preprocessing.tables.flavor must be lattice or stream")
    for section_name, ratio_name in (
        ("tables", "empty_cell_ratio_limit"),
        ("tables", "fragmentation_ratio_limit"),
    ):
        ratio = result[section_name].get(ratio_name)
        if not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
            raise CleanCorpusError(
                f"preprocessing.{section_name}.{ratio_name} must be between 0 and 1"
            )
    for section_name, list_name in (
        ("dehyphenation", "known_terms"),
        ("dehyphenation", "preserve_prefixes"),
    ):
        values = result[section_name].get(list_name, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise CleanCorpusError(
                f"preprocessing.{section_name}.{list_name} must be a string list"
            )
    if any(
        not isinstance(k, str) or not k or not isinstance(v, str) or not v
        for k, v in result["abbreviations"].items()
    ):
        raise CleanCorpusError("Each abbreviation needs non-empty text and expansion")
    if any(
        not isinstance(rule, dict)
        or any(
            not isinstance(rule.get(field), str) or not rule[field]
            for field in ("source", "target", "context")
        )
        for rule in result["ocr_corrections"]
    ):
        raise CleanCorpusError("Each OCR correction needs source, target, and literal context")
    return result


def _remove_furniture_lines(
    raw: str, removals: list[tuple[str, str]], audit: Audit, page: int, block: int
) -> str:
    pending: dict[str, list[str]] = {}
    for line, role in removals:
        key = re.sub(r"\s+", "", line).casefold()
        pending.setdefault(key, []).append(role)
    kept: list[str] = []
    for line in raw.splitlines():
        key = re.sub(r"\s+", "", line.strip()).casefold()
        roles = pending.get(key)
        if roles:
            role = roles.pop(0)
            stage = "header_removed" if role == "header" else "footer_removed"
            audit.record(
                stage,
                line,
                "",
                page,
                block,
                rule="repeated_edge_line",
                reason="Repeated on the configured fraction of pages",
            )
            audit.counts["repeated_header_footer_removed"] += 1
            audit.removed_furniture.append(
                {"page": page + 1, "block": block, "role": role, "text": line}
            )
        else:
            kept.append(line)
    return "\n".join(kept).strip()


def _remove_page_numbers(
    raw: str, kind: str, enabled: bool, audit: Audit, page: int, block: int
) -> str:
    if not enabled or kind in {"table", "equation"}:
        return raw
    if is_page_number(raw, kind):
        audit.record(
            "page_number_removed",
            raw,
            "",
            page,
            block,
            rule="standalone_page_number",
            reason="Whole block is a page number",
        )
        return ""
    kept: list[str] = []
    for line in raw.splitlines():
        if is_page_number(line):
            audit.record(
                "page_number_removed",
                line,
                "",
                page,
                block,
                rule="standalone_page_number",
                reason="Whole line is a page number",
            )
        else:
            kept.append(line)
    return "\n".join(kept)


def _table_header_units(text: str) -> dict[int, str]:
    """Infer only explicit, recognizable unit labels from the first two table rows."""
    units: dict[int, str] = {}
    for line in text.splitlines():
        if not re.match(r"Row [12]:", line):
            continue
        for column, cell in re.findall(r"C(\d+)=([^|]+)", line):
            label = cell.strip()
            lowered = label.casefold()
            if re.search(r"(?:wt\.?%|мас\.%|%)\s*$", lowered):
                units[int(column)] = "%"
            elif re.search(r"(?:секунд(?:а|ы)?|сек|seconds?|secs?|\bs\b)\s*$", lowered):
                units[int(column)] = "сек"
            elif re.match(r"^[ТT].*(?:°|0)\s*[СCсc]\s*$", label):
                # In a temperature heading (T..., 0С), the glyph 0 is a common
                # PDF extraction substitute for the degree mark. The heading context
                # makes Celsius explicit; preserve the source heading verbatim.
                units[int(column)] = "°С"
    return units


def _annotate_table_column_units(
    text: str,
    *,
    page: int,
    block: int,
    audit: Audit,
    normalize: bool,
) -> str:
    """Use table header units with Pint for numeric cells and retain source values."""
    units = _table_header_units(text)
    if not units:
        return text
    lines = text.splitlines()
    for line_index, line in enumerate(lines):
        row = re.match(r"Row (\d+):", line)
        if row is None:
            continue
        row_number = int(row.group(1))
        if row_number <= 2:

            def normalize_header_cell(match: re.Match[str]) -> str:
                column = int(match.group(1))
                original = match.group(2)
                if units.get(column) != "°С":
                    return match.group(0)
                normalized = re.sub(
                    r"0\s*[СCсc]\b",
                    lambda unit_match: f"{unit_match.group()} [unit: °C]",
                    original,
                )
                if normalized != original:
                    audit.record(
                        "unit_header_normalization",
                        original,
                        normalized,
                        page,
                        block,
                        rule="celsius_degree_glyph_in_table_header",
                        confidence=0.99,
                        reason="Recognized 0С as Celsius from the temperature column heading",
                    )
                return f"C{column}={normalized}"

            lines[line_index] = re.sub(r"C(\d+)=([^|]*)", normalize_header_cell, line)
            continue

        def annotate_cell(match: re.Match[str]) -> str:
            column = int(match.group(1))
            raw_value = match.group(2)
            value = raw_value.strip()
            trailing_space = raw_value[len(raw_value.rstrip()) :]
            unit = units.get(column)
            if unit is None or not re.fullmatch(
                r"[+-]?\d+(?:[.,]\d+)?(?:\s*[÷–—-]\s*[+-]?\d+(?:[.,]\d+)?)?", value
            ):
                return match.group(0)
            _, records, _, ambiguous = analyze_quantities(
                f"{value} {unit}", page=page, block=block, normalize=normalize
            )
            audit.quantities.extend(item.as_dict() for item in records)
            audit.counts["number_units_detected"] += len(records)
            audit.counts["number_units_recognized"] += len(records) - ambiguous
            audit.counts["pint_normalized_quantities"] += sum(item.normalized for item in records)
            audit.counts["ambiguous_quantities"] += ambiguous
            if not records or not records[0].normalized or records[0].si_value is None:
                return match.group(0)
            si_suffix = f" {records[0].si_unit}" if records[0].si_unit else ""
            annotated = f"{value} [SI: {records[0].si_value}{si_suffix}]"
            audit.record(
                "unit_normalization",
                value,
                annotated,
                page,
                block,
                rule="pint_table_column_unit",
                confidence=0.99,
                reason=(f"Pint conversion using table column unit {unit}; original value retained"),
            )
            return f"C{column}={annotated}{trailing_space}"

        lines[line_index] = re.sub(r"C(\d+)=([^|]*)", annotate_cell, line)
    return "\n".join(lines)


def _preprocess_table_content(
    content: str,
    *,
    source_id: str,
    page: int,
    block: int,
    policy: dict[str, Any],
    audit: Audit,
    seen_abbreviations: set[str],
) -> str:
    """Run CLEAN's conservative text stages on serialized table cells."""
    text = normalize_unicode(content)
    audit.record("unicode_nfc", content, text, page, block, rule="unicode_nfc")
    if policy["ftfy"]["enabled"]:
        repaired, changed = ftfy_repair(text)
        if changed and repaired != text:
            audit.record("ftfy_repair", text, repaired, page, block, rule="ftfy.fix_text")
            text = repaired
    cleaned = clean_controls(text)
    removed = sum(unicodedata.category(char) == "Cc" and char not in "\n\r\t" for char in text)
    audit.counts["control_codepoints_removed"] += removed
    audit.record("control_cleanup", text, cleaned, page, block, rule="remove_unicode_Cc")
    text = cleaned
    if policy["whitespace"]["enabled"]:
        normalized = normalize_whitespace(text)
        audit.record(
            "whitespace_normalization",
            text,
            normalized,
            page,
            block,
            rule="collapse_repeated_whitespace",
        )
        text = normalized
    if policy["dehyphenation"]["enabled"]:
        text, changes = repair_hyphenation_with_changes(
            text,
            known_terms=set(policy["dehyphenation"]["known_terms"]) or None,
            preserve_prefixes=set(policy["dehyphenation"]["preserve_prefixes"]) or None,
        )
        for before, after in changes:
            audit.record(
                "hyphenation_repair",
                before,
                after,
                page,
                block,
                rule="line_break_hyphen",
                confidence=0.99,
            )
    if policy["ocr"]["detect"]:
        suspects = inspect_ocr_artifacts(text)
        for suspect in suspects:
            suspect.update({"page": page + 1, "block": block, "document": source_id})
        audit.suspects.extend(suspects)
        audit.counts["ocr_suspects"] += len(suspects)
        audit.counts["unresolved_ocr_warnings"] += sum(
            item["disposition"] == "unresolved" for item in suspects
        )
    if policy["ocr"]["auto_fix_high_confidence_only"]:
        text, corrections = correct_ocr(text, policy["ocr_corrections"])
        for before, after in corrections:
            audit.record(
                "ocr_automatic_repairs",
                before,
                after,
                page,
                block,
                rule="approved_context_rule",
                confidence=0.99,
            )
    if policy["units"]["enabled"]:
        text, quantities, changes, ambiguous = analyze_quantities(
            text,
            page=page + 1,
            block=block,
            normalize=policy["units"]["normalize_with_pint"],
        )
        audit.quantities.extend(item.as_dict() for item in quantities)
        audit.counts["number_units_detected"] += len(quantities)
        audit.counts["number_units_recognized"] += len(quantities) - ambiguous
        audit.counts["pint_normalized_quantities"] += sum(item.normalized for item in quantities)
        audit.counts["ambiguous_quantities"] += ambiguous
        for before, after in changes:
            audit.record(
                "unit_normalization",
                before,
                after,
                page,
                block,
                rule="pint_si_conversion",
                confidence=0.99,
                reason="Original table quantity retained with Pint SI equivalent",
            )
        text = _annotate_table_column_units(
            text,
            page=page,
            block=block,
            audit=audit,
            normalize=policy["units"]["normalize_with_pint"],
        )
    text, date_changes = normalize_dates(text)
    for before, after in date_changes:
        audit.record(
            "date_normalization", before, after, page, block, rule="valid_day_month_year_to_iso"
        )
    text, abbreviation_changes = expand_abbreviations(
        text, policy["abbreviations"], seen_abbreviations
    )
    for before, after in abbreviation_changes:
        audit.record(
            "abbreviation_expansion",
            before,
            after,
            page,
            block,
            rule="first_occurrence_dictionary_expansion",
        )
    validate_numeric_values(content, text)
    return text


def _process_document(
    source_id: str,
    structured: dict[str, Any],
    policy: dict[str, Any],
    *,
    source_pdf: Path | None = None,
    source_path: str = "",
    output_path: str = "",
) -> tuple[str, dict[str, Any], Audit]:
    pages = structured.get("pages")
    if not isinstance(pages, list) or not pages:
        raise CleanCorpusError(f"{source_id}: structured output has no pages")
    header_policy = policy["headers"]
    min_fraction = header_policy["min_page_fraction"]
    if "min_repeats" in header_policy:
        min_fraction = max(min_fraction, header_policy["min_repeats"] / len(pages))
    furniture = (
        detect_repeated_furniture(
            pages,
            candidate_lines=header_policy["candidate_lines"],
            min_page_fraction=min_fraction,
        )
        if header_policy["enabled"]
        else {}
    )
    audit = Audit()
    registry = ProtectionRegistry()
    pieces: list[str] = []
    originals: list[str] = []
    seen_abbreviations: set[str] = set()
    block_count = 0
    table_index = 0
    formula_index = 0
    original_characters = 0
    for page_obj in pages:
        page_index = int(page_obj.get("page_idx", 0))
        for block_index, block in enumerate(page_obj.get("blocks", [])):
            block_count += 1
            kind = str(block.get("type", ""))
            raw = block.get("content") or ""
            if not isinstance(raw, str):
                raise CleanCorpusError(
                    f"{source_id}: non-text block content at page {page_index + 1}"
                )
            original_characters += len(raw)
            original = raw
            if (page_index, block_index) in furniture:
                raw = _remove_furniture_lines(
                    raw, furniture[(page_index, block_index)], audit, page_index, block_index
                )
                if not raw.strip():
                    continue
            raw = _remove_page_numbers(
                raw, kind, policy["page_numbers"]["enabled"], audit, page_index, block_index
            )
            if not raw.strip():
                continue
            captions = _captions(block)
            if kind == "equation" and policy["formulas"]["protect"]:
                formula_index += 1
                metadata = formula_metadata(raw, enabled=policy["formulas"]["sympy_validation"])
                metadata.update(
                    {
                        "document": source_id,
                        "page": page_index + 1,
                        "formula_id": f"{source_id}-F{formula_index:03d}",
                    }
                )
                audit.formulas.append(metadata)
                audit.counts["formula_protected"] += 1
                if metadata.get("sympy_valid") is True:
                    audit.counts["formula_validated_sympy"] += 1
                elif metadata.get("sympy_valid") is False:
                    audit.counts["formula_validation_failures"] += 1
                content = serialize_formula(raw, captions)
                marker = registry.protect("formula", content, page_index, block_index)
                pieces.append(marker)
                originals.append(original)
                continue
            if kind == "table" and policy["tables"]["enabled"]:
                table_index += 1
                table_id = f"{source_id}-T{table_index:03d}"
                mineru_result = MinerUTableExtractor().extract(
                    raw,
                    document=source_id,
                    table_id=table_id,
                    page=page_index + 1,
                    empty_cell_limit=policy["tables"]["empty_cell_ratio_limit"],
                    fragmentation_limit=policy["tables"]["fragmentation_ratio_limit"],
                )
                result = mineru_result
                if policy["tables"]["extractor"] == "camelot":
                    if source_pdf is None:
                        raise CleanCorpusError("Camelot table extraction requires the source PDF")
                    camelot_result = CamelotTableExtractor().extract(
                        pdf_path=source_pdf,
                        page=page_index + 1,
                        document=source_id,
                        table_id=table_id,
                        flavor=policy["tables"]["flavor"],
                        minimum_accuracy=policy["tables"]["minimum_accuracy"],
                        maximum_whitespace=policy["tables"]["maximum_whitespace"],
                        original=raw,
                    )
                    if camelot_result.valid:
                        result = camelot_result
                    elif policy["tables"]["fallback_to_mineru"]:
                        mineru_result.issues.insert(
                            0,
                            "Camelot primary rejected: " + "; ".join(camelot_result.issues),
                        )
                        result = mineru_result
                    else:
                        result = camelot_result
                if result.valid and result.extractor in {"Camelot", "MinerU"}:
                    content = result.serialized
                    content = _preprocess_table_content(
                        content,
                        source_id=source_id,
                        page=page_index,
                        block=block_index,
                        policy=policy,
                        audit=audit,
                        seen_abbreviations=seen_abbreviations,
                    )
                    result.serialized = content
                audit.tables.append(result.report())
                audit.counts["tables_from_mineru"] += result.extractor == "MinerU"
                audit.counts["invalid_mineru_tables"] += (
                    result.extractor == "MinerU" and not result.valid
                )
                audit.counts["tables_from_camelot"] += result.extractor == "Camelot"
                if not result.valid:
                    content = (
                        f"[TABLE id={table_id} document={source_id} page={page_index + 1} "
                        f"extractor={result.extractor} raw_preserved]\n{raw}\n[/TABLE]"
                    )
                marker = registry.protect("table", content, page_index, block_index)
                pieces.append(marker)
                # Numeric integrity follows the selected parser, which may replace MinerU OCR.
                originals.append(content)
                audit.counts["table_protected"] += 1
                continue
            if kind in {"image", "chart"} and not raw and captions:
                raw = "Figure: " + " ".join(captions)
            if not raw.strip():
                continue
            originals.append(original)
            inline_registry = ProtectionRegistry()
            text, protected_counts = protect_inline_values(
                raw, inline_registry, policy["abbreviations"], page_index, block_index
            )
            for protected_kind, count in protected_counts.items():
                audit.counts[f"{protected_kind}_protected"] += count
            text_before_nfc = text
            text = normalize_unicode(text)
            audit.record(
                "unicode_nfc",
                text_before_nfc,
                text,
                page_index,
                block_index,
                rule="unicode_nfc",
                reason="Normalize Unicode canonical composition",
            )
            if policy["ftfy"]["enabled"]:
                repaired, changed = ftfy_repair(text)
                if changed and repaired == text:
                    audit.warnings.append(
                        f"Page {page_index + 1} block {block_index}: ftfy change was reverted "
                        "because technical tokens changed"
                    )
                elif changed:
                    audit.record(
                        "ftfy_repair",
                        text,
                        repaired,
                        page_index,
                        block_index,
                        rule="ftfy.fix_text",
                        reason="Encoding repair passed technical-token guard",
                    )
                    text = repaired
            cleaned_controls = clean_controls(text)
            audit.counts["control_codepoints_removed"] += sum(
                unicodedata.category(char) == "Cc" and char not in "\n\r\t" for char in text
            )
            audit.record(
                "control_cleanup",
                text,
                cleaned_controls,
                page_index,
                block_index,
                rule="remove_unicode_Cc",
                reason="Remove control characters, retaining layout whitespace",
            )
            text = cleaned_controls
            if policy["whitespace"]["enabled"]:
                normalized = normalize_whitespace(text)
                audit.record(
                    "whitespace_normalization",
                    text,
                    normalized,
                    page_index,
                    block_index,
                    rule="collapse_repeated_whitespace",
                    reason="Preserve paragraph breaks",
                )
                text = normalized
            if policy["dehyphenation"]["enabled"]:
                known_terms = set(policy["dehyphenation"]["known_terms"])
                preserve_prefixes = set(policy["dehyphenation"]["preserve_prefixes"])
                text, hyphen_changes = repair_hyphenation_with_changes(
                    text,
                    known_terms=known_terms or None,
                    preserve_prefixes=preserve_prefixes or None,
                )
                for before, after in hyphen_changes:
                    audit.record(
                        "hyphenation_repair",
                        before,
                        after,
                        page_index,
                        block_index,
                        rule="line_break_hyphen",
                        confidence=0.99,
                        reason="Known word fragment or conservative Cyrillic split",
                    )
            text = inline_registry.restore(text)
            for protected_kind, count in protected_counts.items():
                audit.counts[f"{protected_kind}_restored"] += count
            if policy["ocr"]["detect"]:
                suspects = inspect_ocr_artifacts(text)
                for suspect in suspects:
                    suspect["page"] = page_index + 1
                    suspect["block"] = block_index
                    suspect["document"] = source_id
                    audit.suspects.append(suspect)
                audit.counts["ocr_suspects"] += len(suspects)
                audit.counts["unresolved_ocr_warnings"] += sum(
                    item["disposition"] == "unresolved" for item in suspects
                )
            if policy["ocr"]["auto_fix_high_confidence_only"]:
                corrected, corrections = correct_ocr(text, policy["ocr_corrections"])
            else:
                corrected, corrections = text, []
            for before, after in corrections:
                audit.record(
                    "ocr_automatic_repairs",
                    before,
                    after,
                    page_index,
                    block_index,
                    rule="approved_context_rule",
                    confidence=0.99,
                    reason="Exact source-target rule with nearby configured context",
                )
            text = corrected
            if policy["units"]["enabled"]:
                text, quantities, unit_changes, ambiguous = analyze_quantities(
                    text,
                    page=page_index + 1,
                    block=block_index,
                    normalize=policy["units"]["normalize_with_pint"],
                )
                audit.quantities.extend(item.as_dict() for item in quantities)
                audit.counts["number_units_detected"] += len(quantities)
                audit.counts["number_units_recognized"] += len(quantities)
                audit.counts["pint_normalized_quantities"] += sum(
                    item.normalized for item in quantities
                )
                audit.counts["ambiguous_quantities"] += ambiguous
                for before, after in unit_changes:
                    audit.record(
                        "unit_normalization",
                        before,
                        after,
                        page_index,
                        block_index,
                        rule="pint_si_conversion",
                        confidence=0.99,
                        reason="Original quantity retained with Pint SI equivalent",
                    )
            text, date_changes = normalize_dates(text)
            for before, after in date_changes:
                audit.record(
                    "date_normalization",
                    before,
                    after,
                    page_index,
                    block_index,
                    rule="valid_day_month_year_to_iso",
                    reason="Keep source date and add ISO date",
                )
            text, abbreviation_changes = expand_abbreviations(
                text, policy["abbreviations"], seen_abbreviations
            )
            for before, after in abbreviation_changes:
                audit.record(
                    "abbreviation_expansion",
                    before,
                    after,
                    page_index,
                    block_index,
                    rule="first_occurrence_dictionary_expansion",
                )
            if text:
                validate_numeric_values(raw, text)
                pieces.append(text)
    text = registry.restore("\n\n".join(pieces).strip() + "\n")
    validate_integrity(text, registry)
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
        "document": source_id,
        "source_format": "MinerU structured_content.json",
        "input_path": source_path,
        "output_path": output_path,
        "page_count": len(pages),
        "block_count": block_count,
        "original_character_count": original_characters,
        "cleaned_character_count": len(text),
        "counts": dict(sorted(audit.counts.items())),
        "unicode_changes": audit.counts["unicode_nfc"],
        "ftfy_changes": audit.counts["ftfy_repair"],
        "control_characters_removed": audit.counts["control_codepoints_removed"],
        "headers_removed": audit.counts["header_removed"],
        "footers_removed": audit.counts["footer_removed"],
        "page_numbers_removed": audit.counts["page_number_removed"],
        "whitespace_repairs": audit.counts["whitespace_normalization"],
        "dehyphenation_repairs": audit.counts["hyphenation_repair"],
        "ocr_suspects": audit.suspects,
        "ocr_automatic_repairs": audit.counts["ocr_automatic_repairs"],
        "unresolved_ocr_warnings": audit.counts["unresolved_ocr_warnings"],
        "number_unit_expressions_detected": audit.counts["number_units_detected"],
        "pint_normalized_quantities": audit.counts["pint_normalized_quantities"],
        "ambiguous_quantities": audit.counts["ambiguous_quantities"],
        "quantities": audit.quantities,
        "tables_from_mineru": audit.counts["tables_from_mineru"],
        "invalid_mineru_tables": audit.counts["invalid_mineru_tables"],
        "tables_from_camelot": audit.counts["tables_from_camelot"],
        "tables": audit.tables,
        "formulas_protected": audit.counts["formula_protected"],
        "formulas_validated_with_sympy": audit.counts["formula_validated_sympy"],
        "formula_validation_failures": audit.counts["formula_validation_failures"],
        "formulas": audit.formulas,
        "removed_headers_footers": audit.removed_furniture,
        "warnings": audit.warnings,
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


def _markdown_summary(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        f"# CLEAN preprocessing: {report['document']}",
        "",
        f"- Input: `{report['input_path']}`",
        f"- Output: `{report['output_path']}`",
        f"- Pages: {report['page_count']}",
        f"- Characters: {report['original_character_count']} → {report['cleaned_character_count']}",
        f"- Integrity: {report['integrity']}",
        "",
        "## Transformations",
        "",
    ]
    lines.extend(f"- `{name}`: {count}" for name, count in sorted(counts.items()))
    lines.extend(["", "## Tables", ""])
    if report["tables"]:
        lines.extend(
            f"- {item['table_id']} page {item['page']}: {item['extractor']}, "
            f"valid={item['valid']}, {item['row_count']}×{item['column_count']}, "
            f"issues={'; '.join(item['issues']) or 'none'}"
            for item in report["tables"]
        )
    else:
        lines.append("- No tables found.")
    lines.extend(["", "## Formula checks", ""])
    if report["formulas"]:
        lines.extend(
            f"- {item['formula_id']} page {item['page']}: SymPy={item['sympy_valid']}; "
            f"{item['warning'] or 'validated'}"
            for item in report["formulas"]
        )
    else:
        lines.append("- No formulas found.")
    lines.extend(["", "## OCR and processing warnings", ""])
    if report["ocr_suspects"] or report["warnings"]:
        lines.extend(
            f"- OCR: page {item['page']}, {item['category']}: {item['text']} — {item['reason']}"
            for item in report["ocr_suspects"]
        )
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- None recorded.")
    lines.append("")
    return "\n".join(lines)


def build_clean_corpus(
    config_path: Path = Path("configs/experiment.yaml"),
    mineru_config_path: Path = Path("configs/mineru.yaml"),
    preprocessing_config_path: Path = Path("configs/preprocessing.yaml"),
) -> CleanCorpusSummary:
    """Validate MinerU extraction, process documents, and publish CLEAN artifacts."""
    validate_extraction(config_path, mineru_config_path)
    experiment = load_experiment(config_path)
    root = config_path.resolve().parent.parent
    with preprocessing_config_path.open(encoding="utf-8") as stream:
        raw_policy = yaml.safe_load(stream)
    if not isinstance(raw_policy, dict):
        raise CleanCorpusError("Preprocessing config must be a YAML mapping")
    policy = _normalize_policy(raw_policy)
    pending: list[tuple[str, str, dict[str, Any], Audit]] = []
    for source in experiment.sources:
        mineru_dir = root / experiment.paths.mineru / source.id
        structured_path = mineru_dir / "structured_content.json"
        structured = json.loads(structured_path.read_text(encoding="utf-8"))
        source_pdf = root / source.path
        target = root / experiment.paths.clean / "input" / f"{source.id}.txt"
        text, report, audit = _process_document(
            source.id,
            structured,
            policy,
            source_pdf=source_pdf,
            source_path=str(structured_path),
            output_path=str(target),
        )
        pending.append((source.id, text, report, audit))
    output_root = root / experiment.paths.clean
    reports_root = root / experiment.paths.reports / "preprocessing"
    documents: list[CleanDocument] = []
    for source_id, content, report, audit in pending:
        input_path = output_root / "input" / f"{source_id}.txt"
        clean_report_path = output_root / "reports" / f"{source_id}.json"
        report_path = reports_root / f"{source_id}.json"
        markdown_path = reports_root / f"{source_id}.md"
        audit_path = output_root / "audit" / f"{source_id}.jsonl"
        report["output_path"] = str(input_path)
        json_content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        _write_atomic(input_path, content)
        _write_atomic(clean_report_path, json_content)
        _write_atomic(report_path, json_content)
        _write_atomic(markdown_path, _markdown_summary(report))
        audit_records = []
        for change in audit.changes:
            record = asdict(change)
            record["document"] = source_id
            record["page"] = int(change.page) + 1
            audit_records.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
            logger.debug(
                "%s page %s block %s %s [%s]: %r -> %r",
                source_id,
                change.page + 1,
                change.block,
                change.stage,
                change.rule,
                change.before,
                change.after,
            )
        _write_atomic(audit_path, "".join(item + "\n" for item in audit_records))
        logger.info(
            "Clean document %s: %s characters; report=%s", source_id, len(content), report_path
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
