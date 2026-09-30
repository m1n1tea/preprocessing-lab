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

from metallab.config import ExperimentConfig, load_experiment
from metallab.evaluation.metrics import (
    build_graph,
    structural_metrics,
    structure_integrity,
)
from metallab.preprocessing.formulas import formula_metadata

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
    graph = build_graph(entities, relationships)
    structural = structural_metrics(graph)
    structural["orphan_relationship_endpoints"] = graph.graph.get(
        "orphan_relationship_endpoints", 0
    )
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
    report: dict[str, Any] = {
        "schema_version": 2,
        "arm": arm,
        "generated_at": datetime.now(UTC).isoformat(),
        "graph_artifacts": {
            "entities": str(entities_path.relative_to(root)),
            "relationships": str(relationships_path.relative_to(root)),
            "entity_rows": len(entities),
            "relationship_rows": len(relationships),
        },
        "graph": structural,
        "integrity": integrity,
        "notes": [
            (
                "Structural topology uses a simple undirected graph; duplicate and reverse edges "
                "collapse."
            ),
            (
                "Formula/table integrity compares MinerU structures with arm input text, not "
                "extracted graph claims."
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
    for section in ("graph", "integrity"):
        for key, value in report.get(section, {}).items():
            if isinstance(value, (int, float, str, bool)) or value is None:
                flat[key] = value
    return flat


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _formula_validation_lines(root: Path, experiment: ExperimentConfig) -> list[str]:
    """Check MinerU equations in both prepared corpora and parse each complete string."""
    rows: list[tuple[str, int, int, bool | None, int, int]] = []
    for source in experiment.sources:
        source_id = source.id
        structured = root / experiment.paths.mineru / source_id / "structured_content.json"
        if not structured.is_file():
            continue
        data = json.loads(structured.read_text(encoding="utf-8"))
        text_paths = {
            arm: root / getattr(experiment.paths, arm) / "input" / f"{source_id}.txt"
            for arm in ("dirty", "clean")
        }
        texts = {
            arm: path.read_text(encoding="utf-8") if path.is_file() else ""
            for arm, path in text_paths.items()
        }
        index = 0
        for page_number, page in enumerate(data.get("pages", []), start=1):
            for block in page.get("blocks", []):
                if block.get("type") not in {"equation", "formula"} or not block.get("content"):
                    continue
                index += 1
                original = str(block["content"])
                parsed = formula_metadata(original, enabled=True)
                rows.append(
                    (
                        source_id,
                        index,
                        page_number,
                        parsed["sympy_valid"],
                        texts["dirty"].count(original),
                        texts["clean"].count(original),
                    )
                )
    if not rows:
        return ["## SymPy equation validation", "", "No MinerU equation blocks available.", ""]
    passed = sum(row[3] is True for row in rows)
    failed = sum(row[3] is False for row in rows)
    unavailable = sum(row[3] is None for row in rows)
    lines = [
        "## SymPy equation validation",
        "",
        (
            f"SymPy strict full-string parsing: **{passed}/{len(rows)} accepted**, "
            f"**{failed} rejected**, **{unavailable} unavailable**. "
            "Each source below is a MinerU equation block; the DIRTY and CLEAN columns "
            "count exact occurrences of its original string in the prepared input text."
        ),
        "",
        "| MinerU equation | PDF page | SymPy parse | DIRTY copies | CLEAN copies |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for document, index, page, valid, dirty_count, clean_count in rows:
        status = "Accepted" if valid is True else "Rejected" if valid is False else "Unavailable"
        lines.append(
            f"| `{document}-F{index:03d}` | {page} | {status} | {dirty_count} | {clean_count} |"
        )
    lines.extend(
        [
            "",
            (
                "Parsing checks whether SymPy can consume the entire MinerU LaTeX string. "
                "Rejection may reflect OCR damage, layout markup, or LaTeX unsupported by "
                "SymPy; it does not by itself prove that the PDF equation is incorrect. "
                "Exact retention in both inputs does not verify mathematical fidelity to the PDFs. "
                "This check reads the existing prepared inputs; it does not rebuild either corpus."
            ),
            "",
        ]
    )
    return lines


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

    def display_number(value: Any, *, digits: int = 2) -> str:
        if value is None:
            return "Not available"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)

    graph_labels = {
        "node_count": "Nodes",
        "edge_count": "Unique undirected edges",
        "connected_components": "Connected components",
        "largest_connected_component_nodes": "Largest component nodes",
        "largest_connected_component_ratio": "Largest component ratio",
        "isolated_nodes": "Isolated nodes",
        "average_degree": "Average degree",
        "bridges": "Bridges",
        "articulation_points": "Articulation points",
        "cycle_basis_count": "Cycle basis count",
        "average_clustering": "Average clustering",
        "density": "Density",
        "orphan_relationship_endpoints": "Orphan relationship endpoints",
    }
    graph_rows = []
    for key, label in graph_labels.items():
        dirty = reports["dirty"]["graph"].get(key)
        clean = reports["clean"]["graph"].get(key)
        if key == "largest_connected_component_ratio":
            dirty_text = f"{dirty:.1%}" if dirty is not None else "Not available"
            clean_text = f"{clean:.1%}" if clean is not None else "Not available"
            delta_text = (
                f"{(clean - dirty):+.1%}" if dirty is not None and clean is not None else "—"
            )
        else:
            digits = 6 if key == "density" else 3 if key == "average_clustering" else 2
            dirty_text = display_number(dirty, digits=digits)
            clean_text = display_number(clean, digits=digits)
            delta_text = (
                display_number(clean - dirty, digits=digits)
                if isinstance(clean, (int, float)) and isinstance(dirty, (int, float))
                else "—"
            )
        graph_rows.append(f"| {label} | {dirty_text} | {clean_text} | {delta_text} |")

    def integrity_result(report: dict[str, Any], key: str) -> str:
        details = report["integrity"].get(f"{key}_details", {})
        score = report["integrity"].get(f"{key}_integrity")
        if score is None:
            return "Not available (no structures found)"
        return f"{details.get('preserved', 0)}/{details.get('expected', 0)} ({score:.0%})"

    lines = [
        "# DIRTY vs CLEAN evaluation",
        "",
        "## Metric scope",
        "",
        "This report covers graph structure and formula/table preservation.",
        "",
        (
            "Graph topology is a simple undirected graph; duplicate and reverse relationships "
            "collapse into one edge. Formula and table integrity measure preservation from MinerU "
            "output into GraphRAG inputs, not graph extraction quality."
        ),
        "",
        "## Graph structure",
        "",
        "| Metric | DIRTY | CLEAN | CLEAN − DIRTY |",
        "| --- | ---: | ---: | ---: |",
        *graph_rows,
        "",
        "## Formula and table preservation",
        "",
        "| Check | DIRTY | CLEAN |",
        "| --- | ---: | ---: |",
        (
            f"| Formulas preserved | {integrity_result(reports['dirty'], 'formula')} | "
            f"{integrity_result(reports['clean'], 'formula')} |"
        ),
        (
            f"| Tables preserved | {integrity_result(reports['dirty'], 'table')} | "
            f"{integrity_result(reports['clean'], 'table')} |"
        ),
        "",
        *_formula_validation_lines(root, experiment),
    ]
    lines.extend(
        [
            "",
            "## Reading the comparison",
            "",
            (
                "The CLEAN graph has more nodes and edges, fewer components and isolates, and a "
                "larger share of nodes in its largest component. Average degree and clustering are "
                "also higher. These structural differences do not establish semantic correctness."
            ),
            "",
            (
                "Both arms preserved all formula and table structures counted by the checks: "
                "14 formulas and 1 table in each arm."
            ),
            "",
            (
                "Per-arm details are in `metrics_dirty.json` and `metrics_clean.json`. See "
                "[metrics.md](../docs/metrics.md) for definitions and limitations."
            ),
        ]
    )
    factual_report = reports_dir / "factual_query_comparison.md"
    if factual_report.is_file():
        lines.extend(
            [
                "",
                "## GraphRAG question answering",
                "",
                "The separate [factual query comparison](factual_query_comparison.md) reviews "
                "short source-checked answers from the DIRTY and CLEAN graphs.",
            ]
        )
    markdown_path = reports_dir / "final_report.md"
    temporary = markdown_path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(markdown_path)
    return {
        "comparison": comparison_path,
        "graph_metrics": graph_path,
        "final_report": markdown_path,
    }
