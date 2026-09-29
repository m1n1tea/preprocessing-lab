"""Independent, conservative transformations for CLEAN MinerU text."""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Any

import regex as re

from metallab.preprocessing.units import QUANTITY_PATTERN
from metallab.preprocessing.units import normalize_units as _normalize_units


@dataclass(frozen=True)
class Change:
    stage: str
    before: str
    after: str
    page: int
    block: int
    rule: str = ""
    confidence: float = 1.0
    reason: str = ""


class Audit:
    def __init__(self) -> None:
        self.changes: list[Change] = []
        self.counts: Counter[str] = Counter()
        self.suspects: list[dict[str, Any]] = []
        self.quantities: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.formulas: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.removed_furniture: list[dict[str, Any]] = []

    def record(
        self,
        stage: str,
        before: str,
        after: str,
        page: int,
        block: int,
        *,
        rule: str = "",
        confidence: float = 1.0,
        reason: str = "",
    ) -> None:
        if before == after:
            return
        matcher = SequenceMatcher(None, before, after, autojunk=False)
        fragments = [
            (before[start_a:end_a], after[start_b:end_b])
            for opcode, start_a, end_a, start_b, end_b in matcher.get_opcodes()
            if opcode != "equal"
        ]
        if not fragments:
            fragments = [(before, after)]
        for before_fragment, after_fragment in fragments:
            self.changes.append(
                Change(
                    stage,
                    before_fragment[:240],
                    after_fragment[:240],
                    page,
                    block,
                    rule,
                    confidence,
                    reason,
                )
            )
            self.counts[stage] += 1


def normalize_unicode(text: str) -> str:
    """NFC preserves compatibility distinctions used in technical notation."""
    return unicodedata.normalize("NFC", text)


def clean_controls(text: str) -> str:
    """Remove C0/C1 controls except line breaks and tabs; keep suspicious Unicode visible."""
    return "".join(char for char in text if char in "\n\r\t" or unicodedata.category(char) != "Cc")


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\f\v\p{Zs}]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalized_furniture_key(text: str) -> str:
    value = normalize_unicode(text)
    value = re.sub(r"\s+", "", value).casefold()
    return value


def detect_repeated_furniture(
    pages: list[dict[str, Any]], *, candidate_lines: int = 4, min_page_fraction: float = 0.6
) -> dict[tuple[int, int], list[tuple[str, str]]]:
    """Find recurring lines near page edges, retaining page/block and header/footer role."""
    if not pages or candidate_lines < 1 or not 0 < min_page_fraction <= 1:
        return {}
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    positions: list[tuple[int, int, int, str, str, str]] = []
    for page in pages:
        page_index = int(page.get("page_idx", 0))
        content_lines: list[tuple[int, int, str, str]] = []
        for block_index, block in enumerate(page.get("blocks", [])):
            content = block.get("content")
            if not isinstance(content, str):
                continue
            kind = str(block.get("type", ""))
            if kind in {"table", "equation", "paragraph_title", "doc_title", "ref_text"}:
                continue
            for line_index, line in enumerate(content.splitlines() or [content]):
                if line.strip():
                    content_lines.append((block_index, line_index, line.strip(), kind))
        top = set((block, line) for block, line, *_ in content_lines[:candidate_lines])
        bottom = set((block, line) for block, line, *_ in content_lines[-candidate_lines:])
        for block_index, line_index, line, kind in content_lines:
            if len(line) < 4:
                continue
            is_top = (block_index, line_index) in top
            is_bottom = (block_index, line_index) in bottom
            roles: list[str] = []
            if kind == "header" or (is_top and kind not in {"page_number"}):
                roles.append("header")
            if kind == "footer" or (is_bottom and kind not in {"page_number"}):
                roles.append("footer")
            for role in set(roles):
                key = (role, normalized_furniture_key(line))
                occurrences[key].add(page_index)
                positions.append((page_index, block_index, line_index, line, role, key[1]))
    minimum = max(2, int(len(pages) * min_page_fraction + 0.999999))
    repeated = {key for key, page_ids in occurrences.items() if len(page_ids) >= minimum}
    removed: dict[tuple[int, int], list[tuple[str, str]]] = defaultdict(list)
    for page, block, _, line, role, key in positions:
        if (role, key) in repeated:
            removed[(page, block)].append((line, role))
    return dict(removed)


def repeated_furniture(pages: list[dict[str, Any]], min_pages: int = 2) -> set[tuple[int, int]]:
    """Backward-compatible block-level view of repeated header/footer detection."""
    removed = detect_repeated_furniture(
        pages,
        candidate_lines=4,
        min_page_fraction=min(min_pages / max(len(pages), 1), 1.0),
    )
    return set(removed)


PAGE_NUMBER = re.compile(
    r"(?i)^(?:(?:page|p\.?|стр\.?|страница)\s*)?\d{1,4}(?:\s*(?:/|из|of)\s*\d{1,4})?$"
)


def is_page_number(text: str, block_type: str = "") -> bool:
    if block_type == "page_number":
        return True
    return bool(PAGE_NUMBER.fullmatch(text.strip()))


HYPHEN_BREAK = re.compile(r"(?P<left>\p{L}{2,})-(?P<gap>\n|[ \t]+)(?P<right>\p{L}{2,})")
REAL_HYPHEN_PREFIXES = {
    "anti",
    "cross",
    "high",
    "inter",
    "intra",
    "low",
    "long",
    "medium",
    "multi",
    "non",
    "over",
    "post",
    "pre",
    "short",
    "under",
    "ultra",
    "well",
}
DEFAULT_DOMAIN_WORDS = {
    "recrystallization",
    "recrystallized",
    "recrystallize",
    "transformation",
    "temperature",
    "deformation",
    "microstructure",
    "precipitation",
    "austenite",
    "ferrite",
    "controlled",
    "cooling",
    "rolling",
    "strengthening",
    "steelmaking",
    "thermomechanical",
}


def repair_hyphenation_with_changes(
    text: str,
    *,
    known_terms: set[str] | None = None,
    preserve_prefixes: set[str] | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []
    known = {term.casefold() for term in (known_terms or DEFAULT_DOMAIN_WORDS)}
    prefixes = preserve_prefixes or REAL_HYPHEN_PREFIXES

    def replacement(match: re.Match[str]) -> str:
        left, right = match["left"], match["right"]
        original = match.group()
        cyrillic = bool(re.fullmatch(r"\p{Script=Cyrillic}+", left + right))
        latin = bool(re.fullmatch(r"\p{Script=Latin}+", left + right))
        if left.casefold() in prefixes:
            result = f"{left}-{right}"
        elif cyrillic and right.islower():
            result = left + right
        elif latin and (left + right).casefold() in known:
            result = left + right
        else:
            return original
        if result != original:
            changes.append((original, result))
        return result

    return HYPHEN_BREAK.sub(replacement, text), changes


def repair_hyphenation(text: str) -> str:
    return repair_hyphenation_with_changes(text)[0]


SUSPECT_TOKEN = re.compile(r"\b(?:[\p{L}]+\d+[\p{L}]+|\d{3,}[\p{L}]+)\b")


def inspect_ocr_artifacts(text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    patterns: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
        (
            "replacement_character",
            re.compile(r"\ufffd"),
            "unresolved",
            "Unicode replacement character",
        ),
        (
            "private_use_character",
            re.compile(r"\p{Co}"),
            "unresolved",
            "Private-use glyph needs source-page review",
        ),
        (
            "mojibake_greek",
            re.compile(r"(?:Î|Ï)[±αβγδεζηθικλμνξοπρστυφχψω]"),
            "review",
            "Possible mojibake in a Greek technical symbol",
        ),
        (
            "degree_notation",
            re.compile(r"(?<!\w)\d+\s+[0ОO]\s*[CСс](?!\w)"),
            "review",
            "Possible corrupted Celsius notation; not auto-corrected",
        ),
        (
            "mixed_alphanumeric",
            SUSPECT_TOKEN,
            "review",
            "Check OCR digits and letters in a technical token",
        ),
    )
    for category, pattern, disposition, reason in patterns:
        for match in pattern.finditer(text):
            results.append(
                {
                    "text": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                    "category": category,
                    "disposition": disposition,
                    "reason": reason,
                    "automatic_repair": False,
                }
            )
    return results


def detect_ocr_suspects(text: str) -> list[str]:
    """Detection-only compatibility helper used by older callers."""
    return [item["text"] for item in inspect_ocr_artifacts(text)]


def correct_ocr(text: str, rules: list[dict[str, str]]) -> tuple[str, list[tuple[str, str]]]:
    """Apply only literal reviewed replacements with their required nearby context."""
    applied: list[tuple[str, str]] = []
    for rule in rules:
        source, target = rule["source"], rule["target"]
        context = rule.get("context", "")
        if not source or not target or not context:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(source) + r"(?!\w)")
        for match in reversed(list(pattern.finditer(text))):
            nearby = (
                text[max(0, match.start() - 120) : match.start()]
                + text[match.end() : match.end() + 120]
            )
            if context not in nearby:
                continue
            text = text[: match.start()] + target + text[match.end() :]
            applied.append((source, target))
    return text, applied


def ftfy_repair(text: str) -> tuple[str, bool]:
    """Repair mojibake only when technical-symbol tokens remain stable."""
    import ftfy

    repaired = ftfy.fix_text(text)
    token_pattern = re.compile(r"[\p{Greek}\p{Letter}\p{Number}_{}\\^°µμ±≤≥≠≈]+")
    technical = re.compile(r"[\p{Greek}\p{Number}_{}\\^°µμ±≤≥≠≈]")
    before = {token for token in token_pattern.findall(text) if technical.search(token)}
    after = {token for token in token_pattern.findall(repaired) if technical.search(token)}
    if before != after:
        return text, repaired != text
    return repaired, repaired != text


@dataclass(frozen=True)
class Protected:
    kind: str
    content: str
    page: int
    block: int


class ProtectionRegistry:
    """Opaque markers protect exact formula/table/value text through generic cleanup."""

    def __init__(self) -> None:
        self.items: dict[str, Protected] = {}

    def protect(self, kind: str, content: str, page: int, block: int) -> str:
        marker = f"⟦{kind.upper()}_{len(self.items):05d}⟧"
        self.items[marker] = Protected(kind, content, page, block)
        return marker

    def restore(self, text: str) -> str:
        for marker, item in self.items.items():
            if text.count(marker) != 1:
                raise ValueError(f"Protected {item.kind} marker missing or duplicated: {marker}")
            text = text.replace(marker, item.content)
        return text


def serialize_table(content: str, captions: list[str]) -> str:
    heading = "Table" + (": " + " ".join(captions) if captions else "")
    return f"{heading}\n{content}" if content else heading


def serialize_formula(content: str, captions: list[str]) -> str:
    heading = "Formula" + (": " + " ".join(captions) if captions else "")
    return f"{heading}\n$$\n{content}\n$$" if content else heading


NUMBER_UNIT = QUANTITY_PATTERN


def normalize_units(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Compatibility wrapper for the shared Pint implementation."""
    return _normalize_units(text)


def protect_inline_values(
    text: str, registry: ProtectionRegistry, abbreviations: dict[str, str], page: int, block: int
) -> tuple[str, Counter[str]]:
    spans: list[tuple[int, int, str, str]] = [
        (match.start(), match.end(), "number_unit", match.group())
        for match in NUMBER_UNIT.finditer(text)
    ]
    for short in abbreviations:
        if not short:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(short) + r"(?!\w)")
        spans.extend(
            (m.start(), m.end(), "abbreviation", m.group()) for m in pattern.finditer(text)
        )
    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))
    selected: list[tuple[int, int, str, str]] = []
    previous_end = -1
    for span in spans:
        if span[0] >= previous_end:
            selected.append(span)
            previous_end = span[1]
    counts: Counter[str] = Counter()
    for start, end, kind, original in reversed(selected):
        marker = registry.protect(kind, original, page, block)
        text = text[:start] + marker + text[end:]
        counts[kind] += 1
    return text, counts


def recognize_number_units(text: str) -> list[str]:
    return [match.group() for match in NUMBER_UNIT.finditer(text)]


DATE = re.compile(r"(?<!\d)(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})(?!\d)")


def normalize_dates(text: str) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []

    def replacement(match: re.Match[str]) -> str:
        original = match.group()
        try:
            iso = date(int(match["year"]), int(match["month"]), int(match["day"])).isoformat()
        except ValueError:
            return original
        result = f"{original} [ISO: {iso}]"
        changes.append((original, result))
        return result

    return DATE.sub(replacement, text), changes


def expand_abbreviations(
    text: str, dictionary: dict[str, str], seen: set[str]
) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []
    for short, full in dictionary.items():
        if short in seen or not short or not full:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(short) + r"(?!\w)")
        match = pattern.search(text)
        if match:
            result = f"{short} [{full}]"
            text = text[: match.start()] + result + text[match.end() :]
            changes.append((short, result))
            seen.add(short)
    return text, changes


def validate_numeric_values(original: str, result: str) -> None:
    before = Counter(re.findall(r"\d+(?:[.,]\d+)?", original))
    after = Counter(re.findall(r"\d+(?:[.,]\d+)?", result))
    missing = before - after
    if missing:
        raise ValueError(f"Source numeric tokens lost: {missing.most_common(5)}")


def validate_integrity(text: str, registry: ProtectionRegistry) -> None:
    if not text.strip():
        raise ValueError("Clean document has no text")
    if re.search(r"⟦[A-Z_]+_\d+⟧", text):
        raise ValueError("Unrestored protected marker in clean text")
    for item in registry.items.values():
        if item.content and item.content not in text:
            raise ValueError(f"Protected {item.kind} content is missing after restoration")
