"""Metric definitions and report behavior for GraphRAG evaluation."""

import json
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from metallab.evaluation.metrics import (
    GoldEntities,
    domain_coverage,
    entity_metrics,
    relation_metrics,
    structural_metrics,
    structure_integrity,
    traversal_metrics,
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


def test_entity_relation_and_noise_metrics_match_manual_gold() -> None:
    gold = [
        {"entity": "Austenite", "aliases": "gamma|γ", "is_noise": "false"},
        {"entity": "Ferrite", "aliases": "alpha|α", "is_noise": "false"},
    ]
    entities = pd.DataFrame({"title": ["γ", "missed"]})
    measured = entity_metrics(entities, gold)
    assert measured["entity_precision"] == 0.5
    assert measured["entity_recall"] == 0.5
    assert measured["noise_ratio"] == 0.5
    assert measured["entity_counts"] == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
    }

    relationships = pd.DataFrame(
        {"source": ["Austenite", "missed"], "target": ["Ferrite", "Ferrite"]}
    )
    relation = relation_metrics(
        relationships,
        [{"source": "γ", "target": "α"}],
        GoldEntities(gold),
    )
    assert relation["relation_precision"] == 0.5
    assert relation["relation_recall"] == 1.0


def test_domain_coverage_supports_pipe_separated_aliases(tmp_path: Path) -> None:
    terms = tmp_path / "domain_terms.txt"
    terms.write_text(
        "austenite|gamma phase\ncontrolled rolling|thermomechanical rolling\n", encoding="utf-8"
    )
    entities = pd.DataFrame(
        {"title": ["γ phase"], "description": ["Controlled rolling refines grains."]}
    )
    result = domain_coverage(entities, terms)
    assert result["domain_coverage"] == 0.5
    assert result["matched_terms"] == ["controlled rolling"]
    assert result["unmatched_terms"] == ["austenite"]


def test_bfs_shortest_path_and_ranked_retrieval_metrics() -> None:
    graph = nx.Graph([("a", "b"), ("b", "c"), ("c", "d")])
    gold = GoldEntities(None)
    result = traversal_metrics(
        graph,
        [
            {
                "query_id": "q1",
                "start_entity": "a",
                "target_entity": "c",
                "expected_entities": "c|missing",
                "noise_entities": "b",
            }
        ],
        gold,
    )
    assert result["bfs_recall_at_2"] == 0.5
    assert result["bfs_noise_ratio_at_2"] == 0.5
    assert result["shortest_path_success_rate"] == 1.0
    assert result["hit_rate_at_10"] == 1.0
    assert 0 < result["mrr"] <= 1
    assert 0 < result["ndcg_at_10"] <= 1


def test_pairwise_coreference_accuracy_uses_raw_entity_resolution() -> None:
    result = entity_metrics(
        pd.DataFrame({"title": ["Austenite"]}),
        [{"entity": "Austenite", "aliases": "gamma phase"}],
        raw_entities=pd.DataFrame({"title": ["Austenite", "gamma phase"]}),
        coreference_rows=[
            {"mention": "Austenite", "canonical_entity": "Austenite"},
            {"mention": "gamma phase", "canonical_entity": "Austenite"},
        ],
    )
    assert result["coreference_accuracy"] == 1.0
    assert result["coreference"]["pair_count"] == 1


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
        "gold: data/gold, reports: reports}\n",
        encoding="utf-8",
    )
    _write_graph(tmp_path / "data/dirty/graphrag/output")
    result = evaluate_arm("dirty", configs / "experiment.yaml")
    assert result["graph"]["node_count"] == 3
    assert result["semantic"]["entity_precision"] is None
    assert result["traversal"]["bfs_recall_at_2"] is None
    assert (tmp_path / "reports/metrics_dirty.json").is_file()
    assert (tmp_path / "reports/dirty_graph.graphml").is_file()
    with pytest.raises(EvaluationError, match="Evaluate both arms"):
        compare_reports(configs / "experiment.yaml")
    clean_report = json.loads((tmp_path / "reports/metrics_dirty.json").read_text())
    clean_report["arm"] = "clean"
    (tmp_path / "reports/metrics_clean.json").write_text(json.dumps(clean_report), encoding="utf-8")
    outputs = compare_reports(configs / "experiment.yaml")
    assert set(outputs) == {"comparison", "graph_metrics", "traversal_metrics", "final_report"}
    assert all(path.is_file() for path in outputs.values())
