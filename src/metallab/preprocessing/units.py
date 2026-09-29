"""Conservative metallurgical quantity recognition and SI annotations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import regex
from pint import UnitRegistry

QUANTITY_PATTERN = regex.compile(
    r"(?<![\p{L}\p{N}_.])"
    r"(?P<number>[+-]?\d+(?:[.,]\d+)?(?:\s*[÷–—-]\s*\d+(?:[.,]\d+)?)?)"
    r"\s*(?P<unit>°\s*[CСс]|℃|degC|°\s*[CСс]\s*/\s*[sс]|"
    r"°\s*[CСс]\s*/\s*min|m³\s*/\s*h|m3\s*/\s*h|m\^3\s*/\s*h|"
    r"N/mm²|N/mm2|Н/мм²|Н/мм2|GPa|ГПа|MPa|МПа|kPa|кПа|Pa|Па|"
    r"µm|μm|мкм|mm|мм|cm|см|m|м|sec(?:ond)?s?|seconds?|секунд(?:а|ы)?|сек|"
    r"min(?:ute)?s?|мин(?:ут(?:а|ы)?)?|h(?:ours?)?|ч(?:ас(?:а|ов)?)?|%|wt\.%|мас\.%|с|K)"
    r"(?![\p{L}\p{N}_/])",
    regex.IGNORECASE,
)

_SI_LABELS = {
    "pascal": "Pa",
    "meter": "m",
    "meter ** 3 / second": "m³/s",
    "second": "s",
    "kelvin": "K",
    "kelvin / second": "K/s",
    "dimensionless": "",
}

_UNIT_MAP: dict[str, tuple[str, str, bool]] = {
    "mpa": ("megapascal", "pascal", True),
    "мпа": ("megapascal", "pascal", True),
    "gpa": ("gigapascal", "pascal", True),
    "гпа": ("gigapascal", "pascal", True),
    "kpa": ("kilopascal", "pascal", True),
    "кпа": ("kilopascal", "pascal", True),
    "pa": ("pascal", "pascal", False),
    "па": ("pascal", "pascal", False),
    "n/mm²": ("newton / millimeter ** 2", "pascal", True),
    "n/mm2": ("newton / millimeter ** 2", "pascal", True),
    "н/мм²": ("newton / millimeter ** 2", "pascal", True),
    "н/мм2": ("newton / millimeter ** 2", "pascal", True),
    "mm": ("millimeter", "meter", True),
    "мм": ("millimeter", "meter", True),
    "cm": ("centimeter", "meter", True),
    "см": ("centimeter", "meter", True),
    "µm": ("micrometer", "meter", True),
    "μm": ("micrometer", "meter", True),
    "мкм": ("micrometer", "meter", True),
    "m": ("meter", "meter", False),
    "м": ("meter", "meter", False),
    "m³/h": ("meter ** 3 / hour", "meter ** 3 / second", True),
    "m3/h": ("meter ** 3 / hour", "meter ** 3 / second", True),
    "m^3/h": ("meter ** 3 / hour", "meter ** 3 / second", True),
    "%": ("percent", "dimensionless", True),
    "wt.%": ("percent", "dimensionless", True),
    "мас.%": ("percent", "dimensionless", True),
    "s": ("second", "second", False),
    "sec": ("second", "second", False),
    "secs": ("second", "second", False),
    "second": ("second", "second", False),
    "seconds": ("second", "second", False),
    "сек": ("second", "second", False),
    "с": ("second", "second", True),
    "секунда": ("second", "second", False),
    "секунды": ("second", "second", False),
    "секунд": ("second", "second", False),
    "min": ("minute", "second", True),
    "mins": ("minute", "second", True),
    "minute": ("minute", "second", True),
    "minutes": ("minute", "second", True),
    "мин": ("minute", "second", True),
    "минута": ("minute", "second", True),
    "минуты": ("minute", "second", True),
    "минут": ("minute", "second", True),
    "h": ("hour", "second", True),
    "hour": ("hour", "second", True),
    "hours": ("hour", "second", True),
    "ч": ("hour", "second", True),
    "час": ("hour", "second", True),
    "часа": ("hour", "second", True),
    "часов": ("hour", "second", True),
    "k": ("kelvin", "kelvin", False),
    "°c": ("degree_Celsius", "kelvin", False),
    "°с": ("degree_Celsius", "kelvin", False),
    "℃": ("degree_Celsius", "kelvin", False),
    "degc": ("degree_Celsius", "kelvin", False),
    "°c/s": ("delta_degree_Celsius / second", "kelvin / second", True),
    "°с/с": ("delta_degree_Celsius / second", "kelvin / second", True),
    "°c/min": ("delta_degree_Celsius / minute", "kelvin / second", True),
    "°с/min": ("delta_degree_Celsius / minute", "kelvin / second", True),
}


@dataclass(frozen=True)
class QuantityRecord:
    raw: str
    value: str
    unit: str
    si_value: str | None
    si_unit: str | None
    page: int
    block: int
    normalized: bool
    ambiguous: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _format_number(value: Any) -> str:
    number = Decimal(str(value)).quantize(Decimal("0.000000000001"))
    if number == number.to_integral_value():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def _unit_key(unit: str) -> str:
    return regex.sub(r"\s+", "", unit).casefold()


def analyze_quantities(
    text: str,
    *,
    page: int,
    block: int,
    registry: UnitRegistry | None = None,
    normalize: bool = True,
) -> tuple[str, list[QuantityRecord], list[tuple[str, str]], int]:
    """Retain source notation, annotate useful SI equivalents, and return audit records."""
    ureg = registry or UnitRegistry(autoconvert_offset_to_baseunit=True)
    records: list[QuantityRecord] = []
    changes: list[tuple[str, str]] = []
    ambiguous_count = 0

    def convert(match: regex.Match[str]) -> str:
        nonlocal ambiguous_count
        raw = match.group()
        unit_text = regex.sub(r"\s+", "", match["unit"])
        key = _unit_key(unit_text)
        mapping = _UNIT_MAP.get(key)
        # A zero followed by Cyrillic С is a common extracted spelling of °С in
        # Russian metallurgical PDFs; do not interpret that heading as zero seconds.
        if key == "с" and regex.fullmatch(r"0+(?:[.,]0+)?", match["number"]):
            return raw
        value_text = regex.sub(r"\s*([÷–—-])\s*", r"\1", match["number"])
        range_match = regex.fullmatch(
            r"(?P<first>[+-]?\d+(?:[.,]\d+)?)(?:[÷–—-](?P<second>[+-]?\d+(?:[.,]\d+)?))?",
            value_text,
        )
        if mapping is None or range_match is None:
            ambiguous_count += 1
            records.append(
                QuantityRecord(
                    raw, match["number"], unit_text, None, None, page, block, False, True
                )
            )
            return raw
        pint_unit, target_unit, annotate = mapping
        if not normalize:
            records.append(
                QuantityRecord(raw, match["number"], unit_text, None, None, page, block, False)
            )
            return raw
        values = [range_match["first"], range_match["second"]]
        try:
            converted: list[str] = []
            for value in values:
                if value is None:
                    continue
                magnitude = Decimal(value.replace(",", "."))
                quantity = ureg.Quantity(float(magnitude), pint_unit).to(target_unit)
                converted.append(_format_number(quantity.magnitude))
            si_value = "–".join(converted)
            si_label = _SI_LABELS.get(target_unit, target_unit)
            records.append(
                QuantityRecord(
                    raw, match["number"], unit_text, si_value, si_label, page, block, True
                )
            )
            if not annotate:
                return raw
            suffix = f" {si_label}" if si_label else ""
            normalized = f"{raw} [SI: {si_value}{suffix}]"
            changes.append((raw, normalized))
            return normalized
        except Exception:  # Unit parsing is deliberately fail-safe for unfamiliar notation.
            ambiguous_count += 1
            records.append(
                QuantityRecord(
                    raw, match["number"], unit_text, None, None, page, block, False, True
                )
            )
            return raw

    result = QUANTITY_PATTERN.sub(convert, text)
    return result, records, changes, ambiguous_count


def normalize_units(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Compatibility helper used by focused stage tests and older callers."""
    result, _, changes, _ = analyze_quantities(text, page=0, block=0)
    return result, changes
