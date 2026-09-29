"""Stage-by-stage command-line entry points."""

import json
import logging
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from metallab.config import ExperimentConfig, load_experiment
from metallab.corpus import DirtyCorpusError, build_dirty_corpus
from metallab.extraction import ExtractionError, run_extraction, validate_extraction
from metallab.graph import WorkspaceError, build_workspaces, validate_workspaces
from metallab.logging_setup import configure_logging
from metallab.preprocessing import CleanCorpusError, build_clean_corpus

app = typer.Typer(help="Metallurgical PDF GraphRAG experiment.", no_args_is_help=True)
extraction_app = typer.Typer(help="Parse and validate the two source PDFs with MinerU.")
app.add_typer(extraction_app, name="extraction")
graph_app = typer.Typer(help="Create and validate paired GraphRAG workspaces.")
app.add_typer(graph_app, name="graph")
logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path("configs/experiment.yaml")


class Arm(StrEnum):
    DIRTY = "dirty"
    CLEAN = "clean"


def _load_or_exit(path: Path) -> ExperimentConfig:
    try:
        return load_experiment(path)
    except (OSError, ValueError, ValidationError) as error:
        logger.error("Cannot load experiment config %s: %s", path, error)
        raise typer.Exit(code=2) from error


def _reserved(stage: str) -> None:
    logger.error("%s is reserved; this stage is not implemented yet", stage)
    raise typer.Exit(code=2)


@app.callback()
def main(
    log_level: Annotated[str, typer.Option(help="Console log level.")] = "INFO",
) -> None:
    """Configure logging for every CLI command."""
    try:
        configure_logging(log_level)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error


@app.command()
def doctor(
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
) -> None:
    """Validate the shared config and confirm both source PDFs are present."""
    experiment = _load_or_exit(config)
    root = config.resolve().parent.parent
    missing = [source.path for source in experiment.sources if not (root / source.path).is_file()]
    if missing:
        for path in missing:
            logger.error("Source PDF is missing: %s", root / path)
        raise typer.Exit(code=1)
    logger.info(
        "Configuration valid: %s; sources=%s; chunking=%s/%s; seed=%s",
        experiment.name,
        ", ".join(source.id for source in experiment.sources),
        experiment.chunking.size,
        experiment.chunking.overlap,
        experiment.seed,
    )


@app.command("config-show")
def config_show(
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
) -> None:
    """Display the validated experiment configuration as JSON."""
    experiment = _load_or_exit(config)
    typer.echo(json.dumps(experiment.model_dump(mode="json"), indent=2))


def _run_extraction_command(config: Path, mineru_config: Path, validate_only: bool) -> None:
    try:
        manifests = (
            validate_extraction(config, mineru_config)
            if validate_only
            else run_extraction(config, mineru_config)
        )
    except (OSError, ValueError, ValidationError, ExtractionError) as error:
        logger.error(
            "MinerU extraction %s: %s", "validation failed" if validate_only else "failed", error
        )
        raise typer.Exit(code=1) from error
    for manifest in manifests:
        stats = manifest["statistics"]
        logger.info(
            "%s: %s pages, %s Markdown characters, %s images",
            manifest["source_id"],
            stats["page_count"],
            stats["markdown_characters"],
            stats["image_files"],
        )


@extraction_app.command("run")
def extraction_run(
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
    mineru_config: Annotated[Path, typer.Option(help="Shared MinerU YAML file.")] = Path(
        "configs/mineru.yaml"
    ),
) -> None:
    """Extract both PDFs into separate MinerU artifact directories."""
    _run_extraction_command(config, mineru_config, validate_only=False)


@extraction_app.command("validate")
def extraction_validate(
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
    mineru_config: Annotated[Path, typer.Option(help="Shared MinerU YAML file.")] = Path(
        "configs/mineru.yaml"
    ),
) -> None:
    """Validate both existing MinerU artifact directories."""
    _run_extraction_command(config, mineru_config, validate_only=True)


@app.command()
def extract(
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
    mineru_config: Annotated[Path, typer.Option(help="Shared MinerU YAML file.")] = Path(
        "configs/mineru.yaml"
    ),
) -> None:
    """Alias for extraction run."""
    _run_extraction_command(config, mineru_config, validate_only=False)


@app.command()
def prepare(
    arm: Annotated[Arm, typer.Option(help="Pipeline arm.")],
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
    mineru_config: Annotated[Path, typer.Option(help="Shared MinerU YAML file.")] = Path(
        "configs/mineru.yaml"
    ),
    preprocessing_config: Annotated[
        Path, typer.Option(help="Clean preprocessing YAML file.")
    ] = Path("configs/preprocessing.yaml"),
) -> None:
    """Prepare an arm's corpus from the common MinerU extraction."""
    try:
        if arm is Arm.CLEAN:
            build_clean_corpus(config, mineru_config, preprocessing_config)
        else:
            build_dirty_corpus(config, mineru_config)
    except (OSError, ValueError, ExtractionError, DirtyCorpusError, CleanCorpusError) as error:
        logger.error("%s corpus creation failed: %s", arm.value, error)
        raise typer.Exit(code=1) from error


@graph_app.command("setup")
def graph_setup(
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
    graphrag_config_dir: Annotated[
        Path, typer.Option(help="Shared GraphRAG config directory.")
    ] = Path("configs/graphrag"),
    embeddings_config: Annotated[
        Path, typer.Option(help="Shared vLLM embedding YAML file.")
    ] = Path("configs/embeddings/vllm.yaml"),
) -> None:
    """Generate both workspace settings from one shared template."""
    try:
        build_workspaces(config, graphrag_config_dir, embeddings_config)
    except (OSError, ValueError, WorkspaceError) as error:
        logger.error("GraphRAG workspace setup failed: %s", error)
        raise typer.Exit(code=1) from error


@graph_app.command("validate")
def graph_validate(
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
    graphrag_config_dir: Annotated[
        Path, typer.Option(help="Shared GraphRAG config directory.")
    ] = Path("configs/graphrag"),
    embeddings_config: Annotated[
        Path, typer.Option(help="Shared vLLM embedding YAML file.")
    ] = Path("configs/embeddings/vllm.yaml"),
    runtime: Annotated[
        bool, typer.Option(help="Require real model credentials and endpoints.")
    ] = False,
) -> None:
    """Validate both workspaces and their shared GraphRAG schema without indexing."""
    try:
        validate_workspaces(config, graphrag_config_dir, embeddings_config, runtime=runtime)
    except (OSError, ValueError, WorkspaceError) as error:
        logger.error("GraphRAG workspace validation failed: %s", error)
        raise typer.Exit(code=1) from error


@app.command()
def index(
    arm: Annotated[Arm, typer.Option(help="Pipeline arm.")],
    config: Annotated[Path, typer.Option(help="Experiment YAML file.")] = DEFAULT_CONFIG,
    graphrag_config_dir: Annotated[
        Path, typer.Option(help="Shared GraphRAG config directory.")
    ] = Path("configs/graphrag"),
    embeddings_config: Annotated[
        Path, typer.Option(help="Shared vLLM embedding YAML file.")
    ] = Path("configs/embeddings/vllm.yaml"),
) -> None:
    """Index one arm only after validating the pair and runtime credentials."""
    try:
        workspaces = validate_workspaces(
            config, graphrag_config_dir, embeddings_config, runtime=True
        )
    except (OSError, ValueError, WorkspaceError) as error:
        logger.error("GraphRAG indexing preflight failed: %s", error)
        raise typer.Exit(code=1) from error
    workspace = next(item for item in workspaces if item.arm == arm.value)
    logger.info("Starting GraphRAG standard indexing for %s: %s", arm.value, workspace.root)
    result = subprocess.run(
        [
            str(Path(sys.executable).parent / "graphrag"),
            "index",
            "--root",
            str(workspace.root),
            "--method",
            "standard",
        ],
        check=False,
    )
    if result.returncode:
        raise typer.Exit(code=result.returncode)


@app.command()
def evaluate(arm: Annotated[Arm, typer.Option(help="Pipeline arm.")]) -> None:
    """Reserve the graph evaluation stage."""
    _reserved(f"evaluate {arm.value}")


@app.command()
def compare() -> None:
    """Reserve the paired comparison stage."""
    _reserved("compare")
