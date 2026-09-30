"""Extraction stage validation without downloading MinerU models."""

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from metallab.extraction import ExtractionError, run_extraction, runner, validate_extraction


def _pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    with path.open("wb") as stream:
        writer.write(stream)


def _project(tmp_path: Path) -> tuple[Path, Path]:
    source_dir = tmp_path / "data/source"
    _pdf(source_dir / "stat3.pdf")
    _pdf(source_dir / "tanaka1981.pdf")
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    experiment = config_dir / "experiment.yaml"
    experiment.write_text(
        "name: test\n"
        "seed: 42\n"
        "sources:\n"
        "  - {id: stat3, path: data/source/stat3.pdf}\n"
        "  - {id: tanaka1981, path: data/source/tanaka1981.pdf}\n"
        "chunking: {size: 800, overlap: 120}\n"
        "paths: {mineru: data/mineru, dirty: data/dirty, clean: data/clean, "
        "reports: reports}\n",
        encoding="utf-8",
    )
    settings = config_dir / "mineru.yaml"
    settings.write_text(
        "tier: basic\nocr_mode: auto\nimage_analysis: true\npage_range: all\n",
        encoding="utf-8",
    )
    return experiment, settings


def _saved_result(output: Path, text: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "markdown.md").write_text(text, encoding="utf-8")
    middle = {
        "pages": [{"page_idx": 0, "blocks": [{"type": "table"}, {"type": "equation"}]}],
        "metadata": {"producer": {"name": "mineru", "version": "4.0.8"}},
        "is_full_document": True,
    }
    (output / "middle_json.json").write_text(json.dumps(middle), encoding="utf-8")
    (output / "structured_content.json").write_text(
        json.dumps({"pages": [{"page_idx": 0, "blocks": []}]}),
        encoding="utf-8",
    )
    image_dir = output / "images"
    image_dir.mkdir()
    (image_dir / "page_0_equation_0.png").write_bytes(b"example")


def test_both_pdfs_keep_separate_identity_and_complete_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, settings = _project(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_parse(source: Path, output: Path, options: runner.MinerUSettings) -> None:
        calls.append((source.stem, options.tier))
        _saved_result(output, f"Text extracted from {source.stem}")

    monkeypatch.setattr(runner, "parse_with_mineru", fake_parse)
    manifests = run_extraction(config, settings)
    validated = validate_extraction(config, settings)

    assert calls == [("stat3", "basic"), ("tanaka1981", "basic")]
    assert [item["source_id"] for item in manifests] == ["stat3", "tanaka1981"]
    assert [item["source_id"] for item in validated] == ["stat3", "tanaka1981"]
    for source_id in ("stat3", "tanaka1981"):
        output = tmp_path / "data/mineru" / source_id
        assert (output / "markdown.md").is_file()
        assert (output / "middle_json.json").is_file()
        assert (output / "structured_content.json").is_file()
        assert (output / "images/page_0_equation_0.png").is_file()
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_id"] == source_id
        assert manifest["source_page_count"] == 1
        assert manifest["statistics"]["table_blocks"] == 1
        assert manifest["statistics"]["formula_blocks"] == 1


def test_missing_source_is_rejected_before_parsing(tmp_path: Path) -> None:
    config, settings = _project(tmp_path)
    (tmp_path / "data/source/tanaka1981.pdf").unlink()

    with pytest.raises(ExtractionError, match="Source PDF is missing"):
        run_extraction(config, settings)

    assert not (tmp_path / "data/mineru/stat3").exists()


def test_image_only_output_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, settings = _project(tmp_path)

    def fake_parse(source: Path, output: Path, options: runner.MinerUSettings) -> None:
        _saved_result(output, "![scan](images/page_0_image_0.png)")

    monkeypatch.setattr(runner, "parse_with_mineru", fake_parse)
    with pytest.raises(ExtractionError, match="produced no text"):
        run_extraction(config, settings)

    assert not (tmp_path / "data/mineru/stat3").exists()
