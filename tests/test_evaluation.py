"""Metric definitions and report behavior for GraphRAG evaluation."""

import json
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from metallab.evaluation.metrics import (
    structural_metrics,
    structure_integrity,
)
from metallab.evaluation.runner import EvaluationError, compare_reports, evaluate_arm


def test_structural_metrics_use_undirected_simple_topology() -> None:
    graph = nx.Graph()
    graph.add_edges_from([("a", "b"), ("b", "c")])
    graph.add_node("isolated")
    result = structural_metrics(graph)
    assert result["node_count"] == 4
    assert result["edge_count"] == 2
    assert result["connected_components"] == 2
    assert result["largest_connected_component_ratio"] == 0.75
    assert result["isolated_nodes"] == 1
    assert result["average_degree"] == 1.0
    assert result["bridges"] == 2
    assert result["articulation_points"] == 1
    assert result["cycle_basis_count"] == 0
    assert result["average_clustering"] == 0.0


def test_formula_and_table_integrity_check_mineru_source_against_arm_input(tmp_path: Path) -> None:
    mineru = tmp_path / "data/mineru/stat3"
    mineru.mkdir(parents=True)
    (mineru / "structured_content.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "blocks": [
                            {"type": "equation", "content": r"sigma = 15 MPa"},
                            {
                                "type": "table",
                                "content": "<table><tr><td>Fe</td><td>15 MPa</td></tr></table>",
                            },
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    inputs = tmp_path / "data/clean/input"
    inputs.mkdir(parents=True)
    (inputs / "stat3.txt").write_text(
        "Formula: sigma = 15 MPa\n<table><tr><td>Fe</td><td>15 MPa</td></tr></table>",
        encoding="utf-8",
    )
    formula = structure_integrity(inputs, tmp_path / "data/mineru", ["stat3"], kind="formula")
    table = structure_integrity(inputs, tmp_path / "data/mineru", ["stat3"], kind="table")
    assert formula["formula_integrity"] == 1.0
    assert table["table_integrity"] == 1.0
    selected_table = structure_integrity(
        inputs,
        tmp_path / "data/mineru",
        ["stat3"],
        kind="table",
        expected_tables=[
            {
                "document": "stat3",
                "page": 1,
                "serialized": "<table><tr><td>Fe</td><td>15 MPa</td></tr></table>",
            }
        ],
    )
    assert selected_table["table_integrity"] == 1.0


def _write_graph(output: Path) -> None:
    output.mkdir(parents=True)
    pd.DataFrame(
        {
            "title": ["Austenite", "Ferrite", "Controlled rolling"],
            "type": ["PHASE", "PHASE", "PROCESS"],
            "description": ["gamma phase", "alpha phase", "rolling process"],
        }
    ).to_parquet(output / "entities.parquet", index=False)
    pd.DataFrame(
        {"source": ["Austenite", "Controlled rolling"], "target": ["Ferrite", "Austenite"]}
    ).to_parquet(output / "relationships.parquet", index=False)
    pd.DataFrame({"title": ["Austenite", "Ferrite"]}).to_parquet(
        output / "raw_entities.parquet", index=False
    )


def test_evaluation_runner_writes_per_arm_json_and_graphml(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "experiment.yaml").write_text(
        "name: test\nseed: 42\nsources:\n  - {id: stat3, path: source/stat3.pdf}\n"
        "  - {id: tanaka1981, path: source/tanaka1981.pdf}\n"
        "chunking: {size: 800, overlap: 120}\n"
        "paths: {mineru: data/mineru, dirty: data/dirty, clean: data/clean, "
        "reports: reports}\n",
        encoding="utf-8",
    )
    _write_graph(tmp_path / "data/dirty/graphrag/output")
    result = evaluate_arm("dirty", configs / "experiment.yaml")
    assert result["graph"]["node_count"] == 3
    assert "semantic" not in result
    assert "domain" not in result
    assert "entity_rows" in result["graph_artifacts"]
    assert "traversal" not in result
    assert (tmp_path / "reports/metrics_dirty.json").is_file()
    assert (tmp_path / "reports/dirty_graph.graphml").is_file()
    with pytest.raises(EvaluationError, match="Evaluate both arms"):
        compare_reports(configs / "experiment.yaml")
    clean_report = json.loads((tmp_path / "reports/metrics_dirty.json").read_text())
    clean_report["arm"] = "clean"
    (tmp_path / "reports/metrics_clean.json").write_text(json.dumps(clean_report), encoding="utf-8")
    outputs = compare_reports(configs / "experiment.yaml")
    assert set(outputs) == {"comparison", "graph_metrics", "final_report"}
    assert all(path.is_file() for path in outputs.values())
    assert "traversal" not in outputs["final_report"].read_text(encoding="utf-8").lower()
