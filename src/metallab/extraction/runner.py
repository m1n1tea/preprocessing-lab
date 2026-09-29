"""Extract both source PDFs with one MinerU configuration."""

import hashlib
import json
import logging
import re
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader

from metallab.config import ExperimentConfig, SourceConfig, load_experiment

logger = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """A source, MinerU run, or saved artifact failed validation."""


class MinerUSettings(BaseModel):
    """Options shared by both source PDFs."""

    model_config = ConfigDict(extra="forbid")

    tier: Literal["flash", "basic", "standard", "advanced"]
    ocr_mode: Literal["auto", "txt", "ocr"]
    image_analysis: bool
    page_range: Literal["all"]


def load_mineru_settings(path: Path) -> MinerUSettings:
    """Read and validate the shared MinerU configuration."""
    with path.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    if not isinstance(raw, dict):
        raise ExtractionError(f"Expected a YAML mapping in {path}")
    return MinerUSettings.model_validate(raw)


def sha256_file(path: Path) -> str:
    """Hash a source PDF without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_pages(path: Path) -> int:
    """Check that a source is a readable, non-empty PDF."""
    if not path.is_file():
        raise ExtractionError(f"Source PDF is missing: {path}")
    if path.stat().st_size == 0:
        raise ExtractionError(f"Source PDF is empty: {path}")
    try:
        count = len(PdfReader(path).pages)
    except Exception as error:
        raise ExtractionError(f"Cannot read source PDF {path}: {error}") from error
    if count == 0:
        raise ExtractionError(f"Source PDF has no pages: {path}")
    return count


def parse_with_mineru(source: Path, output: Path, settings: MinerUSettings) -> None:
    """Use MinerU's complete save path for Markdown, JSON, and image assets."""
    from mineru.parser import parse
    from mineru.parser.writer import FileBasedDataWriter

    result = parse(
        source,
        tier=settings.tier,
        ocr_mode=settings.ocr_mode,
        image_analysis=settings.image_analysis,
        page_range=settings.page_range,
    )
    result.save(FileBasedDataWriter(str(output)))


def _has_text(markdown: str) -> bool:
    """Reject empty output and Markdown consisting only of image references."""
    without_images = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)
    without_tags = re.sub(r"<[^>]+>", "", without_images)
    return any(character.isalpha() for character in without_tags)


def validate_saved_artifacts(output: Path, expected_pages: int) -> dict[str, int]:
    """Check MinerU's saved files, document coverage, and non-empty text."""
    markdown_path = output / "markdown.md"
    middle_path = output / "middle_json.json"
    structured_path = output / "structured_content.json"
    for path in (markdown_path, middle_path, structured_path):
        if not path.is_file():
            raise ExtractionError(f"MinerU artifact is missing: {path}")

    markdown = markdown_path.read_text(encoding="utf-8")
    if not _has_text(markdown):
        raise ExtractionError(f"MinerU produced no text: {markdown_path}")

    try:
        middle = json.loads(middle_path.read_text(encoding="utf-8"))
        structured = json.loads(structured_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ExtractionError(f"Cannot read MinerU JSON in {output}: {error}") from error
    if not isinstance(middle, dict) or middle.get("is_full_document") is not True:
        raise ExtractionError(f"MinerU did not save a full document in {output}")
    pages = middle.get("pages")
    structured_pages = structured.get("pages") if isinstance(structured, dict) else None
    if not isinstance(pages, list) or not isinstance(structured_pages, list):
        raise ExtractionError(f"MinerU page records are missing in {output}")
    page_indices = [page.get("page_idx") for page in pages if isinstance(page, dict)]
    if not all(isinstance(index, int) for index in page_indices) or sorted(page_indices) != list(
        range(expected_pages)
    ):
        raise ExtractionError(
            f"MinerU page coverage mismatch in {output}: "
            f"expected {expected_pages}, got {page_indices}"
        )
    if len(structured_pages) != expected_pages:
        raise ExtractionError(
            f"MinerU structured content has {len(structured_pages)} pages; "
            f"expected {expected_pages} in {output}"
        )

    image_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    image_refs += re.findall(r"<img[^>]+src=[\"\']([^\"\']+)", markdown)
    for image_ref in image_refs:
        if image_ref.startswith("images/") and not (output / image_ref).is_file():
            raise ExtractionError(f"MinerU image reference is missing: {output / image_ref}")

    blocks = [
        block for page in pages for block in page.get("blocks", []) if isinstance(block, dict)
    ]
    block_types = [str(block.get("type", "")).lower() for block in blocks]
    images = output / "images"
    image_count = sum(path.is_file() for path in images.rglob("*")) if images.exists() else 0
    return {
        "page_count": len(pages),
        "markdown_characters": len(markdown),
        "block_count": len(blocks),
        "table_blocks": sum("table" in kind for kind in block_types),
        "formula_blocks": sum("formula" in kind or "equation" in kind for kind in block_types),
        "image_files": image_count,
    }


def _context(
    config_path: Path, mineru_config_path: Path
) -> tuple[Path, ExperimentConfig, MinerUSettings]:
    root = config_path.resolve().parent.parent
    experiment = load_experiment(config_path)
    settings = load_mineru_settings(mineru_config_path)
    return root, experiment, settings


def _manifest(
    source: SourceConfig,
    source_hash: str,
    pdf_pages: int,
    settings: MinerUSettings,
    stats: dict[str, int],
    output: Path,
) -> dict[str, object]:
    return {
        "source_id": source.id,
        "source_path": source.path.as_posix(),
        "source_sha256": source_hash,
        "source_page_count": pdf_pages,
        "mineru_version": version("mineru"),
        "settings": settings.model_dump(),
        "statistics": stats,
        "artifacts": sorted(
            path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()
        ),
    }


def _validate_existing(
    output: Path,
    source: SourceConfig,
    source_hash: str,
    pdf_pages: int,
    settings: MinerUSettings,
) -> dict[str, object]:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise ExtractionError(
            f"Output directory exists without a manifest: {output}. Move it aside before rerunning."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "source_id": source.id,
        "source_sha256": source_hash,
        "source_page_count": pdf_pages,
        "mineru_version": version("mineru"),
        "settings": settings.model_dump(),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ExtractionError(
                f"Existing output {output} has different {key}; move it aside before rerunning"
            )
    validate_saved_artifacts(output, pdf_pages)
    return manifest


def run_extraction(
    config_path: Path = Path("configs/experiment.yaml"),
    mineru_config_path: Path = Path("configs/mineru.yaml"),
) -> list[dict[str, object]]:
    """Parse both PDFs into separate directories using identical MinerU options."""
    root, experiment, settings = _context(config_path, mineru_config_path)
    inputs = [
        (source, root / source.path, source_pages(root / source.path))
        for source in experiment.sources
    ]
    output_root = root / experiment.paths.mineru
    output_root.mkdir(parents=True, exist_ok=True)
    manifests: list[dict[str, object]] = []
    for source, path, pdf_pages in inputs:
        source_hash = sha256_file(path)
        output = output_root / source.id
        if output.exists():
            manifest = _validate_existing(output, source, source_hash, pdf_pages, settings)
            logger.info("Validated existing MinerU output for %s: %s", source.id, output)
            manifests.append(manifest)
            continue
        staging = Path(tempfile.mkdtemp(prefix=f".{source.id}-", dir=output_root))
        logger.info(
            "Extracting %s (%s pages) with MinerU %s, tier=%s",
            source.id,
            pdf_pages,
            version("mineru"),
            settings.tier,
        )
        try:
            parse_with_mineru(path, staging, settings)
            stats = validate_saved_artifacts(staging, pdf_pages)
            manifest = _manifest(source, source_hash, pdf_pages, settings, stats, staging)
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            staging.rename(output)
        except Exception as error:
            raise ExtractionError(
                f"MinerU extraction failed for {source.id}; partial files remain in {staging}: "
                f"{error}"
            ) from error
        logger.info("Saved %s: %s", source.id, output)
        manifests.append(manifest)
    return manifests


def validate_extraction(
    config_path: Path = Path("configs/experiment.yaml"),
    mineru_config_path: Path = Path("configs/mineru.yaml"),
) -> list[dict[str, object]]:
    """Validate complete existing outputs for both configured PDFs."""
    root, experiment, settings = _context(config_path, mineru_config_path)
    manifests: list[dict[str, object]] = []
    for source in experiment.sources:
        path = root / source.path
        pdf_pages = source_pages(path)
        output = root / experiment.paths.mineru / source.id
        manifests.append(_validate_existing(output, source, sha256_file(path), pdf_pages, settings))
    return manifests
