"""Formula parsing must reject incomplete input while preserving source strings."""

import json
from pathlib import Path

from metallab.config import load_experiment
from metallab.evaluation.runner import _formula_validation_lines
from metallab.preprocessing.formulas import formula_metadata


def test_sympy_validation_requires_complete_latex_parse() -> None:
    assert formula_metadata("x = 1", enabled=True)["sympy_valid"] is True
    assert formula_metadata(r"x = 1 \quad . \tag{1}", enabled=True)["sympy_valid"] is False


def test_report_checks_both_prepared_texts(tmp_path: Path) -> None:
    config = tmp_path / "configs" / "experiment.yaml"
    config.parent.mkdir()
    config.write_text(
        "name: test\nseed: 42\nsources:\n"
        "  - {id: stat3, path: data/source/stat3.pdf}\n"
        "  - {id: tanaka1981, path: data/source/tanaka1981.pdf}\n"
        "chunking: {size: 800, overlap: 120}\n"
        "paths: {mineru: data/mineru, dirty: data/dirty, clean: data/clean, "
        "reports: reports}\n",
        encoding="utf-8",
    )
    source = tmp_path / "data/mineru/stat3/structured_content.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({"pages": [{"blocks": [{"type": "equation", "content": "x = 1"}]}]}),
        encoding="utf-8",
    )
    for arm in ("dirty", "clean"):
        text = tmp_path / "data" / arm / "input" / "stat3.txt"
        text.parent.mkdir(parents=True)
        text.write_text("Equation: x = 1", encoding="utf-8")

    lines = _formula_validation_lines(tmp_path, load_experiment(config))
    assert any("1/1 accepted" in line for line in lines)
    assert any("`stat3-F001` | 1 | Accepted | 1 | 1" in line for line in lines)
