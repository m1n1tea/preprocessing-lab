"""Paired GraphRAG settings must differ only in their storage locations."""

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from metallab.cli import app
from metallab.graph import WorkspaceError, build_workspaces, validate_workspaces
from metallab.graph import workspace as graph_workspace

ROOT = Path(__file__).resolve().parents[1]


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    configs = tmp_path / "configs"
    configs.mkdir()
    experiment = configs / "experiment.yaml"
    experiment.write_text(
        "name: paired_test\n"
        "seed: 42\n"
        "sources:\n"
        "  - {id: stat3, path: data/source/stat3.pdf}\n"
        "  - {id: tanaka1981, path: data/source/tanaka1981.pdf}\n"
        "chunking: {size: 800, overlap: 120}\n"
        "paths: {mineru: data/mineru, dirty: data/dirty, clean: data/clean, "
        "reports: reports}\n",
        encoding="utf-8",
    )
    shared = configs / "graphrag"
    shutil.copytree(ROOT / "configs/graphrag", shared)
    embeddings = configs / "embeddings"
    embeddings.mkdir()
    shutil.copy2(ROOT / "configs/embeddings/vllm.yaml", embeddings / "vllm.yaml")
    for arm in ("dirty", "clean"):
        inputs = tmp_path / "data" / arm / "input"
        inputs.mkdir(parents=True)
        (inputs / "stat3.txt").write_text("Steel grade X70 and Nb.", encoding="utf-8")
        (inputs / "tanaka1981.txt").write_text("Controlled rolling of Nb steel.", encoding="utf-8")
    return experiment, shared, embeddings / "vllm.yaml"


def test_workspaces_share_settings_and_use_both_documents(tmp_path: Path) -> None:
    experiment, shared, embeddings = _project(tmp_path)
    dirty, clean = build_workspaces(experiment, shared, embeddings)
    validate_workspaces(experiment, shared, embeddings)
    dirty_settings = yaml.safe_load(dirty.settings.read_text())
    clean_settings = yaml.safe_load(clean.settings.read_text())
    assert graph_workspace._without_locations(dirty_settings) == graph_workspace._without_locations(
        clean_settings
    )
    assert dirty_settings["chunking"]["size"] == 800
    assert dirty_settings["chunking"]["overlap"] == 120
    assert dirty_settings["snapshots"]["graphml"] is True
    assert dirty_settings["snapshots"]["raw_graph"] is True
    assert dirty_settings["input_storage"]["base_dir"] == str(dirty.inputs[0].parent)
    assert clean_settings["input_storage"]["base_dir"] == str(clean.inputs[0].parent)
    assert dirty_settings["input"]["file_pattern"] == clean_settings["input"]["file_pattern"]
    pattern = re.compile(dirty_settings["input"]["file_pattern"])
    assert all(pattern.search(str(path)) for path in dirty.inputs)
    assert all(pattern.search(path.name) for path in dirty.inputs)
    assert not pattern.search(str(dirty.inputs[0].parent / "third.txt"))
    for workspace in (dirty, clean):
        report = json.loads((workspace.root / "validation.json").read_text())
        assert set(report["input_sha256"]) == {"stat3.txt", "tanaka1981.txt"}
        assert report["status"] == "validated"
        assert report["prompt_sha256"]


def test_manual_clean_configuration_drift_fails_validation(tmp_path: Path) -> None:
    experiment, shared, embeddings = _project(tmp_path)
    dirty, clean = build_workspaces(experiment, shared, embeddings)
    settings = yaml.safe_load(clean.settings.read_text())
    settings["extract_graph"]["max_gleanings"] = 2
    clean.settings.write_text(yaml.safe_dump(settings))
    with pytest.raises(WorkspaceError, match="diverged"):
        validate_workspaces(experiment, shared, embeddings)
    assert not (dirty.root / "validation.json").exists()
    assert not (clean.root / "validation.json").exists()


def test_extra_input_document_is_rejected_before_setup(tmp_path: Path) -> None:
    experiment, shared, embeddings = _project(tmp_path)
    (tmp_path / "data/dirty/input/third.txt").write_text("extra")
    with pytest.raises(WorkspaceError, match="exactly"):
        build_workspaces(experiment, shared, embeddings)
    assert not (tmp_path / "data/dirty/graphrag").exists()


def test_index_cli_does_not_launch_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise WorkspaceError("invalid configuration")

    launched = False

    def fake_run(*args: object, **kwargs: object) -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr("metallab.cli.validate_workspaces", reject)
    monkeypatch.setattr("metallab.cli.subprocess.run", fake_run)
    result = CliRunner().invoke(app, ["index", "--arm", "dirty"])
    assert result.exit_code == 1
    assert not launched


def test_runtime_validation_requires_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment, shared, embeddings = _project(tmp_path)
    build_workspaces(experiment, shared, embeddings)
    for name in graph_workspace.REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(WorkspaceError, match="required environment variables"):
        validate_workspaces(experiment, shared, embeddings, runtime=True)
