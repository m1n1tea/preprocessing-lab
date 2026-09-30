"""Validated project-level experiment configuration."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    path: Path


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: int = Field(gt=0)
    overlap: int = Field(ge=0)

    @model_validator(mode="after")
    def overlap_is_smaller_than_size(self) -> Self:
        if self.overlap >= self.size:
            raise ValueError("chunk overlap must be smaller than chunk size")
        return self


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mineru: Path
    dirty: Path
    clean: Path
    reports: Path


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    seed: int
    sources: list[SourceConfig]
    chunking: ChunkingConfig
    paths: PathsConfig

    @model_validator(mode="after")
    def sources_are_unique(self) -> Self:
        if len(self.sources) != 2:
            raise ValueError("experiment must contain exactly two source PDFs")
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("source IDs must be unique")
        if len({source.path for source in self.sources}) != len(self.sources):
            raise ValueError("source paths must be unique")
        return self


def load_experiment(path: Path) -> ExperimentConfig:
    """Load a YAML file and validate the shared experiment settings."""
    with path.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return ExperimentConfig.model_validate(raw)
