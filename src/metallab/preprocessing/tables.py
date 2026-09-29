"""Camelot-primary PDF table extraction with validated MinerU fallback."""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


@dataclass
class TableResult:
    document: str
    table_id: str
    page: int
    extractor: str
    valid: bool
    row_count: int
    column_count: int
    header_available: bool
    empty_cell_ratio: float
    malformed_numeric_cells: list[str]
    fragmented: bool
    issues: list[str]
    serialized: str
    original: str
    parser_flavor: str | None = None
    parsing_accuracy: float | None = None
    parsing_whitespace: float | None = None

    def report(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("original")
        return data


class TableExtractor(Protocol):
    name: str

    def extract(self, **kwargs: Any) -> TableResult: ...


def _clean_camelot_cell(value: Any) -> str:
    text = " ".join(str(value).split()).strip()
    # Camelot can split a printed numeric range where the final digit wraps to a new line.
    if re.search(r"\d\s*[÷–−-]\s*\d", text):
        text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
        text = re.sub(r"(?<=[÷–−])\s+", "", text)
    return text


def serialize_dataframe(frame: pd.DataFrame, table_id: str, page: int, document: str) -> str:
    """Serialize rows without numeric inference or edits outside wrapped ranges."""
    rows: list[str] = [f"[TABLE id={table_id} document={document} page={page} extractor=Camelot]"]
    for row_number, row in enumerate(frame.itertuples(index=False, name=None), start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            text = _clean_camelot_cell(value)
            if text:
                cells.append(f"C{column_number}={text}")
        if cells:
            rows.append(f"Row {row_number}: " + " | ".join(cells))
    rows.append("[/TABLE]")
    return "\n".join(rows)


def _numeric_tokens(frame: pd.DataFrame) -> Counter[str]:
    return Counter(
        token
        for value in frame.to_numpy().ravel().tolist()
        for token in re.findall(r"\d+(?:[.,]\d+)?", str(value))
    )


def validate_camelot_table(
    frame: pd.DataFrame,
    *,
    document: str,
    table_id: str,
    page: int,
    flavor: str,
    accuracy: float,
    whitespace: float,
    minimum_accuracy: float = 70.0,
    maximum_whitespace: float = 40.0,
) -> TableResult:
    normalized = frame.fillna("").map(_clean_camelot_cell)
    cells = normalized.to_numpy().ravel().tolist()
    nonempty = [value for value in cells if value]
    empty_ratio = 1 - len(nonempty) / max(len(cells), 1)
    fragmented_cells = [
        value for value in nonempty if "\ufffd" in value or len(value) > 80 or value.count("\n") > 3
    ]
    fragmented = bool(nonempty) and len(fragmented_cells) / len(nonempty) >= 0.35
    malformed = [
        value
        for value in nonempty
        if re.search(r"(?:\d[A-Za-zА-Яа-яЁё]{2,}\d|[A-Za-zА-Яа-яЁё]{2,}\d{2,})", value)
    ]
    serialized = serialize_dataframe(normalized, table_id, page, document)
    source_numbers = _numeric_tokens(normalized)
    serialized_numbers = Counter(re.findall(r"\d+(?:[.,]\d+)?", serialized))
    issues: list[str] = []
    if normalized.shape[0] < 2 or normalized.shape[1] < 2:
        issues.append("Camelot returned fewer than two rows or columns")
    if empty_ratio > 0.5:
        issues.append(f"High empty-cell ratio ({empty_ratio:.2f})")
    if malformed:
        issues.append(f"Suspicious mixed alphanumeric cells ({len(malformed)})")
    if fragmented:
        issues.append("Possible Camelot cell fragmentation")
    if accuracy < minimum_accuracy:
        issues.append(f"Camelot accuracy {accuracy:.2f} below {minimum_accuracy:.2f}")
    if whitespace > maximum_whitespace:
        issues.append(f"Camelot whitespace {whitespace:.2f} above {maximum_whitespace:.2f}")
    if source_numbers - serialized_numbers:
        issues.append("Numeric tokens changed during Camelot serialization")
    valid = not issues
    return TableResult(
        document=document,
        table_id=table_id,
        page=page,
        extractor="Camelot",
        valid=valid,
        row_count=normalized.shape[0],
        column_count=normalized.shape[1],
        header_available=bool(normalized.shape[0] and normalized.shape[1]),
        empty_cell_ratio=empty_ratio,
        malformed_numeric_cells=malformed,
        fragmented=fragmented,
        issues=issues,
        serialized=serialized,
        original=frame.to_csv(index=False, header=False),
        parser_flavor=flavor,
        parsing_accuracy=accuracy,
        parsing_whitespace=whitespace,
    )


def validate_mineru_table(
    content: str,
    *,
    document: str,
    table_id: str,
    page: int,
    empty_cell_limit: float = 0.5,
    fragmentation_limit: float = 0.35,
) -> TableResult:
    """Validate MinerU HTML as a conservative fallback; preserve it on any concern."""
    try:
        frames = pd.read_html(io.StringIO(content), flavor="lxml")
    except (ValueError, ImportError, TypeError):
        frames = []
    frame = frames[0] if frames else None
    issues: list[str] = []
    if frame is None or frame.empty:
        issues.append("MinerU table HTML could not be parsed")
        return TableResult(
            document,
            table_id,
            page,
            "MinerU",
            False,
            0,
            0,
            False,
            1.0,
            [],
            True,
            issues,
            content,
            content,
        )
    normalized = frame.fillna("").astype(str).map(str.strip)
    cells = normalized.to_numpy().ravel().tolist()
    empty_ratio = sum(not value for value in cells) / max(len(cells), 1)
    malformed = [
        value
        for value in cells
        if value and re.search(r"(?:\d[A-Za-zА-Яа-яЁё]{2,}\d|[A-Za-zА-Яа-яЁё]{2,}\d{2,})", value)
    ]
    source_numbers = Counter(re.findall(r"\d+(?:[.,]\d+)?", content))
    parsed_numbers = _numeric_tokens(normalized)
    if source_numbers - parsed_numbers or parsed_numbers - source_numbers:
        issues.append("Numeric tokens changed during MinerU table parsing")
    nonempty = [value for value in cells if value]
    fragmented_cells = [
        value
        for value in nonempty
        if len(value) > 32 or "\ufffd" in value or re.search(r"[A-Za-zА-Яа-яЁё]{2,}\d{2,}", value)
    ]
    fragmented = bool(nonempty) and len(fragmented_cells) / len(nonempty) >= fragmentation_limit
    if normalized.shape[0] < 2 or normalized.shape[1] < 2:
        issues.append("Table has fewer than two rows or columns")
    if empty_ratio > empty_cell_limit:
        issues.append(f"High empty-cell ratio ({empty_ratio:.2f})")
    if malformed:
        issues.append(f"Suspicious numeric cells ({len(malformed)})")
    if fragmented:
        issues.append("Possible OCR/table fragmentation")
    valid = not issues
    return TableResult(
        document,
        table_id,
        page,
        "MinerU",
        valid,
        normalized.shape[0],
        normalized.shape[1],
        bool(re.search(r"<th\b", content, re.IGNORECASE)),
        empty_ratio,
        malformed,
        fragmented,
        issues,
        content,
        content,
    )


class CamelotTableExtractor:
    """Extract the MinerU-identified PDF page using the selected Camelot flavor."""

    name = "Camelot"

    def extract(
        self,
        pdf_path: Path,
        *,
        page: int,
        document: str,
        table_id: str,
        flavor: str = "lattice",
        minimum_accuracy: float = 70.0,
        maximum_whitespace: float = 40.0,
        original: str = "",
        **_: Any,
    ) -> TableResult:
        try:
            import camelot
        except ImportError as error:
            raise RuntimeError(
                "Camelot is required; install it with `uv sync --extra tables`"
            ) from error
        tables = camelot.read_pdf(str(pdf_path), pages=str(page), flavor=flavor)
        if not tables:
            return TableResult(
                document,
                table_id,
                page,
                "Camelot",
                False,
                0,
                0,
                False,
                1.0,
                [],
                True,
                [f"Camelot {flavor} parser found no table on PDF page {page}"],
                "",
                original,
                parser_flavor=flavor,
            )
        candidates = []
        for table in tables:
            report = table.parsing_report
            accuracy = float(report.get("accuracy", 0.0))
            whitespace = float(report.get("whitespace", 100.0))
            result = validate_camelot_table(
                table.df,
                document=document,
                table_id=table_id,
                page=page,
                flavor=flavor,
                accuracy=accuracy,
                whitespace=whitespace,
                minimum_accuracy=minimum_accuracy,
                maximum_whitespace=maximum_whitespace,
            )
            result.original = original
            candidates.append(result)
        candidates.sort(
            key=lambda item: (
                item.valid,
                item.parsing_accuracy or 0.0,
                -(item.parsing_whitespace or 100.0),
                item.row_count * item.column_count,
            ),
            reverse=True,
        )
        return candidates[0]


class MinerUTableExtractor:
    name = "MinerU"

    def extract(self, content: str, **kwargs: Any) -> TableResult:
        return validate_mineru_table(content, **kwargs)
