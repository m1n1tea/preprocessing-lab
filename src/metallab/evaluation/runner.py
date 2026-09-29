"""Load GraphRAG artifacts and publish reproducible evaluation reports."""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from metallab.config import load_experiment
from metallab.evaluation.metrics import (
    build_graph,
    domain_coverage,
    entity_metrics,
    read_csv_rows,
    relation_metrics,
    structural_metrics,
    structure_integrity,
    traversal_metrics,
)

logger = logging.getLogger(__name__)


class EvaluationError(ValueError):
    """Raised when the artifacts needed for evaluation are unavailable or invalid."""


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _load_parquet(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.is_file():
        raise EvaluationError(f"GraphRAG artifact not found: {path}")
    try:
        frame = pd.read_parquet(path)
    except Exception as error:
        raise EvaluationError(f"Cannot read GraphRAG Parquet {path}: {error}") from error
    missing = required - set(frame.columns)
    if missing:
        raise EvaluationError(f"{path} is missing required columns: {sorted(missing)}")
    return frame


def evaluate_arm(arm: str, config_path: Path = Path("configs/experiment.yaml")) -> dict[str, Any]:
    """Evaluate one indexed workspace and write JSON and GraphML artifacts."""
    if arm not in {"dirty", "clean"}:
        raise EvaluationError(f"Unknown arm {arm!r}; expected 'dirty' or 'clean'")
    experiment = load_experiment(config_path)
    root = config_path.resolve().parent.parent
    output_dir = root / getattr(experiment.paths, arm) / "graphrag" / "output"
    entities_path = output_dir / "entities.parquet"
    relationships_path = output_dir / "relationships.parquet"
    entities = _load_parquet(entities_path, {"title"})
    relationships = _load_parquet(relationships_path, {"source", "target"})
    gold_dir = root / experiment.paths.gold
    gold_entity_rows = read_csv_rows(gold_dir / "entities.csv")
    gold_relation_rows = read_csv_rows(gold_dir / "relations.csv")
    coreference_rows = read_csv_rows(gold_dir / "coreference.csv")
    traversal_rows = read_csv_rows(gold_dir / "traversal_queries.csv")
    raw_entity_path = output_dir / "raw_entities.parquet"
    raw_entities = pd.read_parquet(raw_entity_path) if raw_entity_path.is_file() else None

    semantic = entity_metrics(
        entities,
        gold_entity_rows,
        raw_entities=raw_entities,
        coreference_rows=coreference_rows,
    )
    gold_entities = semantic.pop("_gold_entities")
    semantic.update(relation_metrics(relationships, gold_relation_rows, gold_entities))
    graph = build_graph(entities, relationships, gold_entities)
    structural = structural_metrics(graph)
    structural["orphan_relationship_endpoints"] = graph.graph.get(
        "orphan_relationship_endpoints", 0
    )
    traversal = traversal_metrics(graph, traversal_rows, gold_entities)
    corpus_dir = root / getattr(experiment.paths, arm) / "input"
    mineru_root = root / experiment.paths.mineru
    formulas = structure_integrity(
        corpus_dir, mineru_root, [source.id for source in experiment.sources], kind="formula"
    )
    expected_tables: list[dict[str, Any]] | None = None
    if arm == "clean":
        expected_tables = []
        preprocessing_reports = root / experiment.paths.reports / "preprocessing"
        for source in experiment.sources:
            report_path = preprocessing_reports / f"{source.id}.json"
            if not report_path.is_file():
                report_path = root / experiment.paths.clean / "reports" / f"{source.id}.json"
            if report_path.is_file():
                report_data = json.loads(report_path.read_text(encoding="utf-8"))
                expected_tables.extend(
                    {
                        "document": source.id,
                        "page": table.get("page"),
                        "serialized": table.get("serialized"),
                    }
                    for table in report_data.get("tables", [])
                )
    tables = structure_integrity(
        corpus_dir,
        mineru_root,
        [source.id for source in experiment.sources],
        kind="table",
        expected_tables=expected_tables or None,
    )
    integrity = {
        "formula_integrity": formulas["formula_integrity"],
        "formula_details": formulas,
        "table_integrity": tables["table_integrity"],
        "table_details": tables,
    }
    coverage = domain_coverage(entities, gold_dir / "domain_terms.txt")
    report: dict[str, Any] = {
        "schema_version": 1,
        "arm": arm,
        "generated_at": datetime.now(UTC).isoformat(),
        "graph_artifacts": {
            "entities": str(entities_path.relative_to(root)),
            "relationships": str(relationships_path.relative_to(root)),
            "entity_rows": len(entities),
            "relationship_rows": len(relationships),
        },
        "gold_inputs": {
            "entities": gold_entity_rows is not None,
            "relations": gold_relation_rows is not None,
            "coreference": coreference_rows is not None,
            "domain_terms": (gold_dir / "domain_terms.txt").is_file(),
            "traversal_queries": traversal_rows is not None,
        },
        "graph": structural,
        "semantic": semantic,
        "domain": coverage,
        "integrity": integrity,
        "traversal": traversal,
        "notes": [
            (
                "Structural topology uses a simple undirected graph; duplicate and reverse edges "
                "collapse."
            ),
            (
                "Relation scores use directed source-target pairs because GraphRAG 3.2 has no "
                "predicate column."
            ),
            "Unavailable gold-dependent scores are null, not zero.",
            (
                "Formula/table integrity compares MinerU structures with arm input text, not "
                "extracted graph claims."
            ),
            (
                "Retrieval metrics rank reachable nodes by BFS distance, then degree, then name. "
                "They are graph-neighborhood proxies, not GraphRAG LLM search scores."
            ),
        ],
    }
    reports_dir = root / experiment.paths.reports
    report_path = reports_dir / f"metrics_{arm}.json"
    graphml_path = reports_dir / f"{arm}_graph.graphml"
    reports_dir.mkdir(parents=True, exist_ok=True)
    graph_for_graphml = graph.copy()
    nx.write_graphml(graph_for_graphml, graphml_path)
    _atomic_json(report_path, report)
    logger.info(
        "Evaluated %s graph: %s nodes, %s edges; report=%s",
        arm,
        structural["node_count"],
        structural["edge_count"],
        report_path,
    )
    return report


def _flatten(report: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {"arm": report["arm"]}
    for section in ("graph", "semantic", "domain", "integrity", "traversal"):
        for key, value in report.get(section, {}).items():
            if isinstance(value, (int, float, str, bool)) or value is None:
                flat[key] = value
    return flat


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def compare_reports(config_path: Path = Path("configs/experiment.yaml")) -> dict[str, Path]:
    """Compare prior arm reports and create the project CSV and Markdown outputs."""
    experiment = load_experiment(config_path)
    root = config_path.resolve().parent.parent
    reports_dir = root / experiment.paths.reports
    reports: dict[str, dict[str, Any]] = {}
    for arm in ("dirty", "clean"):
        path = reports_dir / f"metrics_{arm}.json"
        if not path.is_file():
            raise EvaluationError(f"Evaluate both arms before comparing; missing {path}")
        reports[arm] = json.loads(path.read_text(encoding="utf-8"))
    flat = {arm: _flatten(report) for arm, report in reports.items()}
    keys = sorted((set(flat["dirty"]) | set(flat["clean"])) - {"arm"})
    comparison = []
    for key in keys:
        dirty, clean = flat["dirty"].get(key), flat["clean"].get(key)
        delta = (
            clean - dirty
            if isinstance(clean, (int, float)) and isinstance(dirty, (int, float))
            else None
        )
        comparison.append(
            {"metric": key, "dirty": dirty, "clean": clean, "clean_minus_dirty": delta}
        )
    comparison_path = reports_dir / "comparison.csv"
    _write_csv(comparison_path, comparison, ["metric", "dirty", "clean", "clean_minus_dirty"])

    graph_keys = sorted(set(reports["dirty"]["graph"]) | set(reports["clean"]["graph"]))
    graph_rows = [
        {"arm": arm, **{key: report["graph"].get(key) for key in graph_keys}}
        for arm, report in reports.items()
    ]
    graph_path = reports_dir / "graph_metrics.csv"
    _write_csv(graph_path, graph_rows, ["arm", *graph_keys])
    traversal_keys = sorted(set(reports["dirty"]["traversal"]) | set(reports["clean"]["traversal"]))
    traversal_rows = [
        {
            "arm": arm,
            **{
                key: report["traversal"].get(key)
                for key in traversal_keys
                if key != "query_metrics"
            },
        }
        for arm, report in reports.items()
    ]
    traversal_path = reports_dir / "traversal_metrics.csv"
    _write_csv(
        traversal_path,
        traversal_rows,
        ["arm", *[key for key in traversal_keys if key != "query_metrics"]],
    )

    lines = [
        "# Dirty vs clean evaluation",
        "",
        (
            "Metrics come from the per-arm JSON reports. Null values indicate unavailable gold "
            "data or missing judgments."
        ),
        "",
        "| Metric | Dirty | Clean | Clean − dirty |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in comparison:
        lines.append(
            f"| {row['metric']} | {row['dirty']} | {row['clean']} | {row['clean_minus_dirty']} |"
        )
    markdown_path = reports_dir / "final_report.md"
    temporary = markdown_path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(markdown_path)
    return {
        "comparison": comparison_path,
        "graph_metrics": graph_path,
        "traversal_metrics": traversal_path,
        "final_report": markdown_path,
    }
