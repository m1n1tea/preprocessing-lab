"""Checks for shared experiment invariants."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from metallab.config import ChunkingConfig, ExperimentConfig, load_experiment


def test_repository_experiment_has_two_sources_and_shared_chunking() -> None:
    path = Path(__file__).resolve().parents[1] / "configs/experiment.yaml"
    experiment = load_experiment(path)

    assert [source.id for source in experiment.sources] == ["stat3", "tanaka1981"]
    assert (experiment.chunking.size, experiment.chunking.overlap) == (800, 120)
    assert experiment.seed == 42


def test_overlap_cannot_equal_chunk_size() -> None:
    with pytest.raises(ValidationError, match="overlap must be smaller"):
        ChunkingConfig(size=800, overlap=800)


def test_duplicate_source_id_is_rejected() -> None:
    path = Path(__file__).resolve().parents[1] / "configs/experiment.yaml"
    raw = load_experiment(path).model_dump()
    raw["sources"][1]["id"] = raw["sources"][0]["id"]

    with pytest.raises(ValidationError, match="source IDs must be unique"):
        ExperimentConfig.model_validate(raw)
