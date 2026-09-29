"""End-to-end checks for structured MinerU clean corpus publication."""

import json
from pathlib import Path

import pytest

from metallab.preprocessing import build_clean_corpus
from metallab.preprocessing import runner as clean_runner


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    configs = tmp_path / "configs"
    configs.mkdir()
    experiment = configs / "experiment.yaml"
    experiment.write_text(
        "name: clean_test\n"
        "seed: 42\n"
        "sources:\n"
        "  - {id: stat3, path: data/source/stat3.pdf}\n"
        "  - {id: tanaka1981, path: data/source/tanaka1981.pdf}\n"
        "chunking: {size: 800, overlap: 120}\n"
        "paths: {mineru: data/mineru, dirty: data/dirty, clean: data/clean, "
        "gold: data/gold, reports: reports}\n",
        encoding="utf-8",
    )
    mineru = configs / "mineru.yaml"
    mineru.write_text("tier: basic\n", encoding="utf-8")
    policy = configs / "preprocessing.yaml"
    policy.write_text(
        "repeated_furniture_min_pages: 2\n"
        "ocr_corrections: []\n"
        "abbreviations: {КП: контролируемая прокатка}\n",
        encoding="utf-8",
    )
    return experiment, mineru, policy


def _structured(tmp_path: Path, source_id: str, pages: list[dict]) -> None:
    path = tmp_path / "data/mineru" / source_id / "structured_content.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pages": pages}, ensure_ascii=False), encoding="utf-8")


def test_clean_corpus_preserves_structures_and_writes_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment, mineru, policy = _project(tmp_path)
    table = "<table><tr><td>15 MPa</td></tr></table>"
    formula = r"\sigma = 15\,\mathrm{MPa}"
    _structured(
        tmp_path,
        "stat3",
        [
            {
                "page_idx": 0,
                "blocks": [
                    {"type": "header", "content": "Journal"},
                    {"type": "text", "content": "КП 15 MPa 31.12.1981"},
                    {"type": "table", "content": table, "captions": []},
                ],
            },
            {
                "page_idx": 1,
                "blocks": [
                    {"type": "header", "content": "Journal"},
                    {"type": "equation", "content": formula, "captions": []},
                ],
            },
        ],
    )
    _structured(
        tmp_path,
        "tanaka1981",
        [
            {
                "page_idx": 0,
                "blocks": [
                    {"type": "header", "content": "138 Reference title"},
                    {"type": "text", "content": "Fe3C and 20 mm"},
                ],
            }
        ],
    )
    monkeypatch.setattr(clean_runner, "validate_extraction", lambda *_: [])
    summary = build_clean_corpus(experiment, mineru, policy)
    assert len(summary.documents) == 2
    stat3 = (tmp_path / "data/clean/input/stat3.txt").read_text(encoding="utf-8")
    tanaka = (tmp_path / "data/clean/input/tanaka1981.txt").read_text(encoding="utf-8")
    assert "Journal" not in stat3
    assert table in stat3 and formula in stat3
    assert "15 MPa [SI: 15000000 Pa]" in stat3
    assert "31.12.1981 [ISO: 1981-12-31]" in stat3
    assert "138 Reference title" in tanaka
    report = json.loads((tmp_path / "data/clean/reports/stat3.json").read_text())
    assert report["counts"]["repeated_header_footer_removed"] == 2
    assert report["counts"]["table_restored"] == 1
    assert report["counts"]["formula_restored"] == 1
    assert report["integrity"] == "passed"
    audit = (tmp_path / "data/clean/audit/stat3.jsonl").read_text()
    assert "unit_normalization" in audit and "date_normalization" in audit
    assert any(
        json.loads(line)["stage"] in {"header_removed", "footer_removed"}
        for line in audit.splitlines()
    )
    before = (stat3, tanaka, audit)
    build_clean_corpus(experiment, mineru, policy)
    assert before == (
        (tmp_path / "data/clean/input/stat3.txt").read_text(),
        (tmp_path / "data/clean/input/tanaka1981.txt").read_text(),
        (tmp_path / "data/clean/audit/stat3.jsonl").read_text(),
    )


def test_invalid_second_document_does_not_publish_partial_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment, mineru, policy = _project(tmp_path)
    _structured(tmp_path, "stat3", [{"page_idx": 0, "blocks": [{"type": "text", "content": "ok"}]}])
    _structured(tmp_path, "tanaka1981", [])
    monkeypatch.setattr(clean_runner, "validate_extraction", lambda *_: [])
    with pytest.raises(clean_runner.CleanCorpusError, match="no pages"):
        build_clean_corpus(experiment, mineru, policy)
    assert not (tmp_path / "data/clean/input").exists()


def test_incomplete_ocr_rule_is_rejected_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment, mineru, policy = _project(tmp_path)
    policy.write_text(
        "repeated_furniture_min_pages: 2\n"
        "ocr_corrections: [{source: rol1ed, target: rolled}]\n"
        "abbreviations: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(clean_runner, "validate_extraction", lambda *_: [])
    with pytest.raises(clean_runner.CleanCorpusError, match="literal context"):
        build_clean_corpus(experiment, mineru, policy)
    assert not (tmp_path / "data/clean/input").exists()
