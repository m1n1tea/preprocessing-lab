"""The dirty corpus must retain MinerU Markdown exactly."""

import logging
from pathlib import Path

import pytest

from metallab.corpus import DirtyCorpusError, build_dirty_corpus, dirty


def _project(tmp_path: Path) -> tuple[Path, Path]:
    configs = tmp_path / "configs"
    configs.mkdir()
    experiment = configs / "experiment.yaml"
    experiment.write_text(
        "name: dirty_test\n"
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
    mineru.write_text(
        "tier: basic\nocr_mode: auto\nimage_analysis: true\npage_range: all\n",
        encoding="utf-8",
    )
    return experiment, mineru


def _markdown(tmp_path: Path, source_id: str, content: bytes) -> None:
    path = tmp_path / "data/mineru" / source_id / "markdown.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_dirty_files_are_byte_identical_to_mineru_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config, mineru = _project(tmp_path)
    stat3 = (
        "HEADER\r\nКП-\r\nУО 730–8000С; 09Г2ФБ; O/0, l/1.\r\n"
        "| T | 15 MPa |\r\nGв = 870 − 1076(Тз − Тс).\r\n"
    ).encode()
    tanaka = (
        "  Tanaka 1981\r\nnon-\r\nrecrystallization; Nb(C,N); "
        "a\u0301 / á; 10\u00a0MPa.\r\n"
        "![figure](images/page_0_chart_1.jpg)\r\n"
    ).encode("utf-8")
    _markdown(tmp_path, "stat3", stat3)
    _markdown(tmp_path, "tanaka1981", tanaka)
    monkeypatch.setattr(dirty, "validate_extraction", lambda *_: [])

    with caplog.at_level(logging.INFO, logger="metallab.corpus.dirty"):
        summary = build_dirty_corpus(config, mineru)

    assert (tmp_path / "data/dirty/input/stat3.txt").read_bytes() == stat3
    assert (tmp_path / "data/dirty/input/tanaka1981.txt").read_bytes() == tanaka
    assert summary.document_count == 2
    assert summary.character_count == len(stat3.decode("utf-8")) + len(tanaka.decode("utf-8"))
    assert "Dirty corpus complete: 2 documents" in caplog.text


def test_missing_second_markdown_creates_no_partial_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, mineru = _project(tmp_path)
    _markdown(tmp_path, "stat3", b"Unchanged text")
    monkeypatch.setattr(dirty, "validate_extraction", lambda *_: [])

    with pytest.raises(DirtyCorpusError, match="Cannot read MinerU Markdown"):
        build_dirty_corpus(config, mineru)

    assert not (tmp_path / "data/dirty/input").exists()


def test_non_utf8_markdown_is_rejected_without_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, mineru = _project(tmp_path)
    _markdown(tmp_path, "stat3", b"bad utf8: \xff")
    _markdown(tmp_path, "tanaka1981", b"other text")
    monkeypatch.setattr(dirty, "validate_extraction", lambda *_: [])

    with pytest.raises(DirtyCorpusError, match="not UTF-8"):
        build_dirty_corpus(config, mineru)

    assert not (tmp_path / "data/dirty/input").exists()
