"""Small, independently testable transformations for MinerU text blocks."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Change:
    stage: str
    before: str
    after: str
    page: int
    block: int


class Audit:
    def __init__(self) -> None:
        self.changes: list[Change] = []
        self.counts: Counter[str] = Counter(
            {
                stage: 0
                for stage in (
                    "unicode_nfc",
                    "control_cleanup",
                    "whitespace_normalization",
                    "repeated_header_footer_removed",
                    "page_number_removed",
                    "hyphenation_repair",
                    "ocr_suspects",
                    "ocr_correction",
                    "formula_protected",
                    "formula_restored",
                    "table_protected",
                    "table_restored",
                    "number_unit_protected",
                    "number_unit_restored",
                    "abbreviation_protected",
                    "abbreviation_restored",
                    "number_units_recognized",
                    "unit_normalization",
                    "date_normalization",
                    "abbreviation_expansion",
                    "integrity_validated",
                )
            }
        )
        self.suspects: list[dict[str, Any]] = []

    def record(self, stage: str, before: str, after: str, page: int, block: int) -> None:
        if before != after:
            self.changes.append(Change(stage, before, after, page, block))
            self.counts[stage] += 1


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def clean_controls(text: str) -> str:
    """Remove control codes while retaining line breaks and tabs for later stages."""
    return "".join(char for char in text if char in "\n\r\t" or unicodedata.category(char) != "Cc")


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def repeated_furniture(pages: list[dict[str, Any]], min_pages: int = 2) -> set[tuple[int, int]]:
    """Identify recurring header/footer text; unique misclassified blocks survive."""
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    for page in pages:
        for block in page["blocks"]:
            if block.get("type") in {"header", "footer"} and block.get("content", "").strip():
                key = (block["type"], re.sub(r"\s+", "", block["content"]).casefold())
                occurrences[key].add(page["page_idx"])
    repeated = {key for key, indices in occurrences.items() if len(indices) >= min_pages}
    return {
        (page["page_idx"], index)
        for page in pages
        for index, block in enumerate(page["blocks"])
        if block.get("type") in {"header", "footer"}
        and (block["type"], re.sub(r"\s+", "", block.get("content", "")).casefold()) in repeated
    }


# MinerU may flatten PDF line wraps to either newline or a single space.
# Inline joining is limited to Cyrillic, as stat3 has many attested split words;
# Latin technical compounds such as "Ni- content" remain untouched.
HYPHEN_BREAK = re.compile(
    r"(?P<left>[^\W\d_]{2,})-(?P<gap>\n| +)(?P<right>[^\W\d_]{2,})",
    re.UNICODE,
)


def repair_hyphenation_with_changes(text: str) -> tuple[str, list[tuple[str, str]]]:
    changes: list[tuple[str, str]] = []

    def replacement(match: re.Match[str]) -> str:
        left, right = match["left"], match["right"]
        cyrillic = bool(re.fullmatch(r"[А-Яа-яЁё]+", left + right))
        safe = cyrillic and right.islower()
        if not safe:
            return match.group()
        result = left + right
        changes.append((match.group(), result))
        return result

    return HYPHEN_BREAK.sub(replacement, text), changes


def repair_hyphenation(text: str) -> str:
    return repair_hyphenation_with_changes(text)[0]


SUSPECT_TOKEN = re.compile(r"\b(?:[A-Za-zА-Яа-яЁё]+\d+[A-Za-zА-Яа-яЁё]+|\d{3,}[A-Za-zА-Яа-яЁё]+)\b")


def detect_ocr_suspects(text: str) -> list[str]:
    """Flag mixed letter/digit tokens for review without changing them."""
    return [match.group() for match in SUSPECT_TOKEN.finditer(text)]


def correct_ocr(text: str, rules: list[dict[str, str]]) -> tuple[str, list[tuple[str, str]]]:
    """Apply only explicitly reviewed whole-token replacements with literal context."""
    applied: list[tuple[str, str]] = []
    for rule in rules:
        source, target = rule["source"], rule["target"]
        context = rule.get("context", "")
        if not source or not target or not context:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(source) + r"(?!\w)")
        for match in reversed(list(pattern.finditer(text))):
            if (
                context not in text[max(0, match.start() - 120) : match.start()]
                and context not in text[match.end() : match.end() + 120]
            ):
                continue
            text = text[: match.start()] + target + text[match.end() :]
            applied.append((source, target))
    return text, applied


@dataclass(frozen=True)
class Protected:
    kind: str
    content: str
    page: int
    block: int


class ProtectionRegistry:
    """Opaque markers protect exact formula/table text through prose cleanup."""

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
    """Keep MinerU's HTML unchanged; add only a readable block label/caption."""
    heading = "Table" + (": " + " ".join(captions) if captions else "")
    return f"{heading}\n{content}" if content else heading


def serialize_formula(content: str, captions: list[str]) -> str:
    heading = "Formula" + (": " + " ".join(captions) if captions else "")
    return f"{heading}\n$$\n{content}\n$$" if content else heading


NUMBER_UNIT = re.compile(
    r"(?<![\w.])(?P<number>\d+(?:[.,]\d+)?)"
    r"(?:(?P<range_sep>[–—-])(?P<number2>\d+(?:[.,]\d+)?))?"
    r"(?P<space>\s*)"
    r"(?P<unit>N/mm²|N/mm2|Н/мм²|Н/мм2|MPa|МПа|GPa|ГПа|mm|мм|cm|см|"
    r"µm|μm|мкм|°C|°С|wt\.%|мас\.%|%|сек|min|мин|\bс|\bK)"
    r"(?![\w/])",
    re.IGNORECASE,
)
UNIT_FACTORS: dict[str, tuple[str, Decimal]] = {
    "mpa": ("Pa", Decimal("1000000")),
    "мпа": ("Pa", Decimal("1000000")),
    "gpa": ("Pa", Decimal("1000000000")),
    "гпа": ("Pa", Decimal("1000000000")),
    "n/mm²": ("Pa", Decimal("1000000")),
    "n/mm2": ("Pa", Decimal("1000000")),
    "н/мм²": ("Pa", Decimal("1000000")),
    "н/мм2": ("Pa", Decimal("1000000")),
    "mm": ("m", Decimal("0.001")),
    "мм": ("m", Decimal("0.001")),
    "cm": ("m", Decimal("0.01")),
    "см": ("m", Decimal("0.01")),
    "µm": ("m", Decimal("0.000001")),
    "μm": ("m", Decimal("0.000001")),
    "мкм": ("m", Decimal("0.000001")),
    "мин": ("s", Decimal("60")),
    "min": ("s", Decimal("60")),
    "сек": ("s", Decimal("1")),
    "с": ("s", Decimal("1")),
}


def protect_inline_values(
    text: str, registry: ProtectionRegistry, abbreviations: dict[str, str], page: int, block: int
) -> tuple[str, Counter[str]]:
    """Seal numeric units and configured abbreviations before prose cleanup."""
    spans: list[tuple[int, int, str, str]] = [
        (match.start(), match.end(), "number_unit", match.group())
        for match in NUMBER_UNIT.finditer(text)
    ]
    for short in abbreviations:
        if not short:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(short) + r"(?!\w)")
        spans.extend(
            (match.start(), match.end(), "abbreviation", match.group())
            for match in pattern.finditer(text)
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


def _decimal_text(number: Decimal) -> str:
    return (
        format(number, "f").rstrip("0").rstrip(".")
        if number % 1
        else format(number, "f").split(".")[0]
    )


def normalize_units(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Append SI equivalents only for unambiguous units, retaining source text."""
    changes: list[tuple[str, str]] = []

    def replacement(match: re.Match[str]) -> str:
        original = match.group()
        factor = UNIT_FACTORS.get(match["unit"].casefold())
        if factor is None:
            return original  # Celsius is recognized but no context-free SI conversion.
        value = Decimal(match["number"].replace(",", ".")) * factor[1]
        normalized = _decimal_text(value)
        if match["number2"] is not None:
            second = Decimal(match["number2"].replace(",", ".")) * factor[1]
            normalized += match["range_sep"] + _decimal_text(second)
        result = f"{original} [SI: {normalized} {factor[0]}]"
        changes.append((original, result))
        return result

    return NUMBER_UNIT.sub(replacement, text), changes


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
    """Reject loss of any source number, even when annotations add new numbers."""
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
