"""Create the dirty GraphRAG corpus without changing MinerU text."""

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from metallab.config import load_experiment
from metallab.extraction import validate_extraction

logger = logging.getLogger(__name__)


class DirtyCorpusError(RuntimeError):
    """MinerU Markdown cannot be copied into the dirty corpus."""


@dataclass(frozen=True)
class DirtyDocument:
    """A copied document and its byte/character counts."""

    source_id: str
    input_path: Path
    characters: int
    byte_count: int


@dataclass(frozen=True)
class DirtyCorpusSummary:
    """Counts for the complete two-document dirty corpus."""

    documents: tuple[DirtyDocument, ...]

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def character_count(self) -> int:
        return sum(document.characters for document in self.documents)


def _write_exact_bytes(destination: Path, content: bytes) -> None:
    """Replace one output atomically, without decoding or changing its bytes."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_dirty_corpus(
    config_path: Path = Path("configs/experiment.yaml"),
    mineru_config_path: Path = Path("configs/mineru.yaml"),
) -> DirtyCorpusSummary:
    """Copy both validated MinerU Markdown files into one dirty input folder.

    No text transformation occurs. The destination bytes are identical to the
    source bytes; UTF-8 decoding is used only to validate and count characters.
    """
    validate_extraction(config_path, mineru_config_path)
    experiment = load_experiment(config_path)
    root = config_path.resolve().parent.parent

    pending: list[tuple[str, bytes, int]] = []
    for source in experiment.sources:
        markdown_path = root / experiment.paths.mineru / source.id / "markdown.md"
        try:
            content = markdown_path.read_bytes()
        except OSError as error:
            raise DirtyCorpusError(f"Cannot read MinerU Markdown: {markdown_path}") from error
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DirtyCorpusError(f"MinerU Markdown is not UTF-8: {markdown_path}") from error
        if not text.strip():
            raise DirtyCorpusError(f"MinerU Markdown is empty: {markdown_path}")
        pending.append((source.id, content, len(text)))

    output_dir = root / experiment.paths.dirty / "input"
    output_dir.mkdir(parents=True, exist_ok=True)
    documents: list[DirtyDocument] = []
    for source_id, content, character_count in pending:
        destination = output_dir / f"{source_id}.txt"
        if not destination.is_file() or destination.read_bytes() != content:
            _write_exact_bytes(destination, content)
        document = DirtyDocument(
            source_id=source_id,
            input_path=destination,
            characters=character_count,
            byte_count=len(content),
        )
        documents.append(document)
        logger.info(
            "Dirty corpus document %s: %s characters, %s bytes -> %s",
            source_id,
            character_count,
            len(content),
            destination,
        )
    summary = DirtyCorpusSummary(documents=tuple(documents))
    logger.info(
        "Dirty corpus complete: %s documents, %s characters",
        summary.document_count,
        summary.character_count,
    )
    return summary
