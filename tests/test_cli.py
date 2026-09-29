"""CLI smoke tests for phase-1 commands."""

from pathlib import Path

from typer.testing import CliRunner

from metallab.cli import app

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def test_doctor_accepts_repository_configuration() -> None:
    result = runner.invoke(app, ["doctor", "--config", str(ROOT / "configs/experiment.yaml")])

    assert result.exit_code == 0
    assert "Configuration valid" in result.output


def test_clean_stage_runs_from_repository_configuration() -> None:
    result = runner.invoke(app, ["prepare", "--arm", "clean"])

    assert result.exit_code == 0
    assert "Clean corpus complete: 2 documents" in result.output
    import json

    report = json.loads((ROOT / "reports/preprocessing/stat3.json").read_text())
    table = report["tables"][0]
    assert table["extractor"] == "Camelot"
    assert table["valid"] is True
    assert table["parser_flavor"] == "lattice"
    assert table["row_count"] == 7
