"""Create and validate paired Microsoft GraphRAG 3.2 workspaces."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from graphrag.config.load_config import load_config as load_graphrag_config

from metallab.config import ExperimentConfig, load_experiment

logger = logging.getLogger(__name__)
ARMS = ("dirty", "clean")
REQUIRED_ENV = (
    "GENERATION_API_BASE_URL",
    "GENERATION_API_KEY",
    "GENERATION_MODEL",
    "EMBEDDING_API_KEY",
)
PATH_FIELDS = (
    ("input_storage", "base_dir"),
    ("output_storage", "base_dir"),
    ("update_output_storage", "base_dir"),
    ("reporting", "base_dir"),
    ("cache", "storage", "base_dir"),
    ("vector_store", "db_uri"),
)
OFFLINE_VALUES = {
    "GENERATION_API_BASE_URL": "https://example.invalid/v1",
    "GENERATION_API_KEY": "offline-validation-placeholder",
    "GENERATION_MODEL": "offline-validation-model",
    "EMBEDDING_API_KEY": "EMPTY",
}


class WorkspaceError(RuntimeError):
    """The two GraphRAG workspaces are missing or have diverged."""


@dataclass(frozen=True)
class Workspace:
    arm: str
    root: Path
    settings: Path
    inputs: tuple[Path, ...]


def _read_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise WorkspaceError(f"Expected YAML mapping: {path}")
    return value


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path: Path, content: str) -> None:
    from tempfile import NamedTemporaryFile

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _project_paths(config_path: Path, experiment: ExperimentConfig, arm: str) -> Workspace:
    project_root = config_path.resolve().parent.parent
    arm_dir = experiment.paths.dirty if arm == "dirty" else experiment.paths.clean
    root = (project_root / arm_dir / "graphrag").resolve()
    input_dir = (project_root / arm_dir / "input").resolve()
    inputs = tuple(input_dir / f"{source.id}.txt" for source in experiment.sources)
    return Workspace(arm, root, root / "settings.yaml", inputs)


def _check_inputs(workspace: Workspace) -> dict[str, str]:
    expected = {path.name for path in workspace.inputs}
    actual = {path.name for path in workspace.inputs[0].parent.glob("*.txt")}
    if actual != expected:
        raise WorkspaceError(
            f"{workspace.arm} input files must be exactly {sorted(expected)}; "
            f"found {sorted(actual)}"
        )
    hashes: dict[str, str] = {}
    for path in workspace.inputs:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            raise WorkspaceError(f"Empty GraphRAG input: {path}")
        hashes[path.name] = _hash(path)
    return hashes


def _settings_for(
    workspace: Workspace,
    experiment: ExperimentConfig,
    template: dict,
    embeddings: dict,
    entity_types: list[str],
    prompt_dir: Path,
) -> dict:
    result = deepcopy(template)
    names = "|".join(re.escape(source.id) for source in experiment.sources)
    result["input"]["file_pattern"] = rf"(?:^|/)(?:{names})\.txt\Z"
    result["chunking"]["size"] = experiment.chunking.size
    result["chunking"]["overlap"] = experiment.chunking.overlap
    result["embedding_models"]["default_embedding_model"]["model"] = embeddings["model"]
    result["embedding_models"]["default_embedding_model"]["api_base"] = embeddings["api_base"]
    result["vector_store"]["vector_size"] = embeddings["dimensions"]
    result["extract_graph"]["entity_types"] = entity_types
    result["cluster_graph"]["seed"] = experiment.seed
    root = workspace.root
    locations = {
        ("input_storage", "base_dir"): str(workspace.inputs[0].parent),
        ("output_storage", "base_dir"): str(root / "output"),
        ("update_output_storage", "base_dir"): str(root / "update_output"),
        ("reporting", "base_dir"): str(root / "logs"),
        ("cache", "storage", "base_dir"): str(root / "cache"),
        ("vector_store", "db_uri"): str(root / "output" / "lancedb"),
    }
    for keys, value in locations.items():
        cursor = result
        for key in keys[:-1]:
            cursor = cursor[key]
        cursor[keys[-1]] = value

    def prompt_paths(node: object) -> object:
        if isinstance(node, dict):
            return {key: prompt_paths(value) for key, value in node.items()}
        if isinstance(node, list):
            return [prompt_paths(value) for value in node]
        if isinstance(node, str) and node.startswith("__PROMPT_DIR__/"):
            return str(prompt_dir / node.removeprefix("__PROMPT_DIR__/"))
        return node

    return prompt_paths(result)


def _inputs_and_settings(
    config_path: Path, graphrag_config_dir: Path, embeddings_config_path: Path
) -> tuple[ExperimentConfig, dict, dict, list[str], Path]:
    experiment = load_experiment(config_path)
    template = _read_yaml(graphrag_config_dir / "settings.template.yaml")
    embeddings = _read_yaml(embeddings_config_path)
    entities = _read_yaml(graphrag_config_dir / "entity_types.yaml").get("entity_types")
    if (
        not isinstance(entities, list)
        or not entities
        or not all(isinstance(x, str) and x for x in entities)
    ):
        raise WorkspaceError("entity_types.yaml must contain a non-empty string list")
    if len(set(entities)) != len(entities):
        raise WorkspaceError("Entity types must be unique")
    if not isinstance(embeddings.get("model"), str) or not embeddings["model"]:
        raise WorkspaceError("Embedding model name is required")
    if not isinstance(embeddings.get("dimensions"), int) or embeddings["dimensions"] <= 0:
        raise WorkspaceError("Positive embedding dimensions are required")
    endpoint = urlparse(str(embeddings.get("api_base", "")))
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise WorkspaceError("Embedding API base must be an HTTP URL")
    prompt_dir = (graphrag_config_dir / "prompts").resolve()
    return experiment, template, embeddings, entities, prompt_dir


def build_workspaces(
    config_path: Path = Path("configs/experiment.yaml"),
    graphrag_config_dir: Path = Path("configs/graphrag"),
    embeddings_config_path: Path = Path("configs/embeddings/vllm.yaml"),
) -> tuple[Workspace, Workspace]:
    """Write both settings from one template after checking both corpora."""
    experiment, template, embeddings, entities, prompt_dir = _inputs_and_settings(
        config_path, graphrag_config_dir, embeddings_config_path
    )
    workspaces = tuple(_project_paths(config_path, experiment, arm) for arm in ARMS)
    for workspace in workspaces:
        _check_inputs(workspace)
    for workspace in workspaces:
        settings = _settings_for(workspace, experiment, template, embeddings, entities, prompt_dir)
        _write_atomic(
            workspace.settings, yaml.safe_dump(settings, allow_unicode=True, sort_keys=False)
        )
        logger.info("Created %s GraphRAG workspace: %s", workspace.arm, workspace.root)
    return (workspaces[0], workspaces[1])


def _without_locations(settings: dict) -> dict:
    result = deepcopy(settings)
    for keys in PATH_FIELDS:
        cursor = result
        for key in keys[:-1]:
            cursor = cursor[key]
        cursor[keys[-1]] = "<arm-specific-path>"
    return result


def _prompt_hashes(settings: dict, prompt_dir: Path) -> dict[str, str]:
    paths: set[Path] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str) and value.endswith(".txt") and "prompts/" in value:
            paths.add(Path(value))

    collect(settings)
    if not paths:
        raise WorkspaceError("No shared GraphRAG prompts configured")
    hashes: dict[str, str] = {}
    for path in sorted(paths):
        if (
            path.parent != prompt_dir
            or not path.is_file()
            or not path.read_text(encoding="utf-8").strip()
        ):
            raise WorkspaceError(f"Missing or empty shared prompt: {path}")
        hashes[path.name] = _hash(path)
    return hashes


def _runtime_environment(project_root: Path, runtime: bool) -> dict[str, str]:
    load_dotenv(project_root / ".env", override=False)
    if runtime:
        missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
        if missing:
            raise WorkspaceError(
                f"Set required environment variables before indexing: {', '.join(missing)}"
            )
        endpoint = urlparse(os.environ["GENERATION_API_BASE_URL"])
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise WorkspaceError("GENERATION_API_BASE_URL must be an HTTP URL")
        if endpoint.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise WorkspaceError("Generation API must be a remote endpoint")
        return {name: os.environ[name] for name in REQUIRED_ENV}
    return {name: os.getenv(name) or placeholder for name, placeholder in OFFLINE_VALUES.items()}


def validate_workspaces(
    config_path: Path = Path("configs/experiment.yaml"),
    graphrag_config_dir: Path = Path("configs/graphrag"),
    embeddings_config_path: Path = Path("configs/embeddings/vllm.yaml"),
    *,
    runtime: bool = False,
) -> tuple[Workspace, Workspace]:
    """Validate paired files, native GraphRAG schema and environment without indexing."""
    experiment, template, embeddings, entities, prompt_dir = _inputs_and_settings(
        config_path, graphrag_config_dir, embeddings_config_path
    )
    workspaces = tuple(_project_paths(config_path, experiment, arm) for arm in ARMS)
    environment = _runtime_environment(config_path.resolve().parent.parent, runtime)
    selected_embedding = os.getenv("EMBEDDING_MODEL")
    if selected_embedding and selected_embedding != embeddings["model"]:
        raise WorkspaceError("EMBEDDING_MODEL differs from configs/embeddings/vllm.yaml")
    common: dict | None = None
    prompt_hashes: dict[str, str] | None = None
    pending_reports: list[tuple[Path, str]] = []
    for workspace in workspaces:
        input_hashes = _check_inputs(workspace)
        if not workspace.settings.is_file():
            raise WorkspaceError(
                f"Missing workspace settings; run graph setup: {workspace.settings}"
            )
        actual = _read_yaml(workspace.settings)
        expected = _settings_for(workspace, experiment, template, embeddings, entities, prompt_dir)
        if actual != expected:
            raise WorkspaceError(
                f"{workspace.arm} settings diverged from shared template or expected paths"
            )
        canonical = _without_locations(actual)
        if common is not None and canonical != common:
            raise WorkspaceError(
                "Dirty and clean GraphRAG settings differ outside storage locations"
            )
        common = canonical
        current_prompts = _prompt_hashes(actual, prompt_dir)
        if prompt_hashes is not None and current_prompts != prompt_hashes:
            raise WorkspaceError("Dirty and clean GraphRAG prompts differ")
        prompt_hashes = current_prompts
        with patch.dict(os.environ, environment):
            native = load_graphrag_config(workspace.root)
        if (
            native.chunking.size != experiment.chunking.size
            or native.chunking.overlap != experiment.chunking.overlap
        ):
            raise WorkspaceError("GraphRAG chunking differs from experiment configuration")
        if not native.snapshots.graphml or not native.snapshots.raw_graph:
            raise WorkspaceError("GraphML and raw graph snapshots must be enabled")
        if native.extract_graph.entity_types != entities:
            raise WorkspaceError("GraphRAG entity types differ from shared list")
        completion = native.completion_models["default_completion_model"]
        embedding = native.embedding_models["default_embedding_model"]
        if (
            completion.model != environment["GENERATION_MODEL"]
            or completion.api_base != environment["GENERATION_API_BASE_URL"]
        ):
            raise WorkspaceError(
                "Generation model or endpoint did not resolve from the environment"
            )
        if embedding.model != embeddings["model"] or embedding.api_base != embeddings["api_base"]:
            raise WorkspaceError("Embedding model or endpoint differs from shared vLLM config")
        if native.vector_store.vector_size != embeddings["dimensions"]:
            raise WorkspaceError("Vector store dimensions differ from the embedding config")
        if native.input_storage.base_dir != str(workspace.inputs[0].parent):
            raise WorkspaceError("GraphRAG input storage points outside the arm corpus")
        if native.output_storage.base_dir != str(workspace.root / "output"):
            raise WorkspaceError("GraphRAG output storage points outside the arm workspace")
        report = {
            "arm": workspace.arm,
            "mode": "runtime" if runtime else "offline",
            "status": "validated",
            "service_connectivity_checked": False,
            "python_version": sys.version.split()[0],
            "graphrag_version": version("graphrag"),
            "input_sha256": input_hashes,
            "settings_sha256": _hash(workspace.settings),
            "shared_settings_sha256": hashlib.sha256(
                json.dumps(canonical, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "prompt_sha256": current_prompts,
            "chunking": {"size": native.chunking.size, "overlap": native.chunking.overlap},
            "entity_types": entities,
            "embedding_model": embeddings["model"],
            "generation_model": os.getenv("GENERATION_MODEL") if runtime else None,
            "snapshots": {
                "graphml": native.snapshots.graphml,
                "raw_graph": native.snapshots.raw_graph,
            },
        }
        pending_reports.append(
            (
                workspace.root / "validation.json",
                json.dumps(report, indent=2, sort_keys=True) + "\n",
            )
        )
        logger.info(
            "Validated %s GraphRAG workspace (%s): %s",
            workspace.arm,
            report["mode"],
            workspace.root,
        )
    for report_path, content in pending_reports:
        _write_atomic(report_path, content)
    return (workspaces[0], workspaces[1])
