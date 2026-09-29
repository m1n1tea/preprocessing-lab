"""Pure graph, gold-label, traversal, retrieval, and integrity metrics."""

from __future__ import annotations

import csv
import html
import itertools
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd


def normalize_label(value: Any) -> str:
    """Normalize labels for deterministic matching without stemming or translation."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).casefold()
    return " ".join(text.split())


def split_values(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [part.strip() for part in re.split(r"[|;]", str(value)) if part.strip()]


def read_csv_rows(path: Path) -> list[dict[str, str]] | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _field(row: dict[str, Any], *names: str) -> str:
    by_lower = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        value = by_lower.get(name.casefold())
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip()
    return ""


def _truth(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "noise"}


class GoldEntities:
    """Gold aliases, positive entity set, and explicit noise labels."""

    def __init__(self, rows: list[dict[str, str]] | None):
        self.available = rows is not None and bool(rows)
        self.rows = rows or []
        self.aliases: dict[str, str] = {}
        self.positive: set[str] = set()
        self.noise: set[str] = set()
        self.has_noise_labels = False
        for row in self.rows:
            canonical = _field(row, "canonical_entity", "entity", "name", "title")
            if not canonical:
                continue
            key = normalize_label(canonical)
            is_noise = _field(row, "is_noise", "noise")
            self.has_noise_labels |= bool(is_noise)
            (self.noise if _truth(is_noise) else self.positive).add(key)
            values = [canonical, *split_values(_field(row, "aliases", "alias"))]
            for value in values:
                self.aliases[normalize_label(value)] = key

    def resolve(self, value: Any) -> str:
        normalized = normalize_label(value)
        return self.aliases.get(normalized, normalized)


def entity_metrics(
    predicted_entities: pd.DataFrame,
    gold_rows: list[dict[str, str]] | None,
    *,
    raw_entities: pd.DataFrame | None = None,
    coreference_rows: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    gold = GoldEntities(gold_rows)
    names = [normalize_label(v) for v in predicted_entities.get("title", []) if normalize_label(v)]
    predicted = set(names)
    if not gold.available:
        precision = recall = noise_ratio = None
        tp = fp = fn = None
        reason = "data/gold/entities.csv is missing or empty"
    else:
        mapped = {gold.resolve(value) for value in predicted}
        tp = len(mapped & gold.positive)
        fp = len(mapped - gold.positive)
        fn = len(gold.positive - mapped)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        noise_ratio = fp / len(mapped) if mapped else None
        reason = None
    coreference = coreference_accuracy(
        predicted_entities,
        raw_entities,
        coreference_rows,
        gold,
    )
    return {
        "entity_precision": precision,
        "entity_recall": recall,
        "entity_counts": {"true_positive": tp, "false_positive": fp, "false_negative": fn},
        "noise_ratio": noise_ratio,
        "coreference_accuracy": coreference["accuracy"],
        "coreference": coreference,
        "entity_gold_available": gold.available,
        "entity_metric_unavailable_reason": reason,
        "_gold_entities": gold,
    }


def coreference_accuracy(
    predicted_entities: pd.DataFrame,
    raw_entities: pd.DataFrame | None,
    gold_rows: list[dict[str, str]] | None,
    gold: GoldEntities,
) -> dict[str, Any]:
    if not gold_rows:
        return {"accuracy": None, "pair_count": 0, "resolved_mentions": 0, "mention_count": 0}
    predicted_titles = {
        gold.resolve(value)
        for value in predicted_entities.get("title", [])
        if normalize_label(value)
    }
    raw_to_final: dict[str, str] = {}
    if raw_entities is not None and "title" in raw_entities:
        for value in raw_entities["title"].dropna().tolist():
            mention = normalize_label(value)
            mapped = gold.resolve(value)
            if mapped in predicted_titles:
                raw_to_final[mention] = mapped
            elif mention in predicted_titles:
                raw_to_final[mention] = mention
    records: list[tuple[str, str, str]] = []
    for row in gold_rows:
        mention = _field(row, "mention", "surface", "name", "alias")
        canonical = _field(row, "canonical_entity", "entity", "cluster")
        if mention and canonical:
            records.append((mention, normalize_label(canonical), normalize_label(mention)))
    if len(records) < 2:
        return {
            "accuracy": None,
            "pair_count": 0,
            "resolved_mentions": sum(norm in raw_to_final for _, _, norm in records),
            "mention_count": len(records),
        }
    correct = 0
    pair_count = 0
    for (_mention_a, gold_a, norm_a), (_mention_b, gold_b, norm_b) in itertools.combinations(
        records, 2
    ):
        pred_a = raw_to_final.get(norm_a, f"unresolved:{norm_a}")
        pred_b = raw_to_final.get(norm_b, f"unresolved:{norm_b}")
        correct += (pred_a == pred_b) == (gold.resolve(gold_a) == gold.resolve(gold_b))
        pair_count += 1
    resolved = sum(norm in raw_to_final for _, _, norm in records)
    return {
        "accuracy": correct / pair_count if pair_count else None,
        "pair_count": pair_count,
        "resolved_mentions": resolved,
        "mention_count": len(records),
        "resolution_coverage": resolved / len(records) if records else None,
    }


def relation_metrics(
    predicted_relationships: pd.DataFrame,
    gold_rows: list[dict[str, str]] | None,
    gold_entities: GoldEntities,
) -> dict[str, Any]:
    if not gold_rows:
        return {
            "relation_precision": None,
            "relation_recall": None,
            "relation_counts": {
                "true_positive": None,
                "false_positive": None,
                "false_negative": None,
            },
            "relation_gold_available": False,
        }
    source_col = "source" if "source" in predicted_relationships else None
    target_col = "target" if "target" in predicted_relationships else None
    if not source_col or not target_col:
        return {
            "relation_precision": None,
            "relation_recall": None,
            "relation_counts": {
                "true_positive": None,
                "false_positive": None,
                "false_negative": None,
            },
            "relation_gold_available": True,
            "relation_metric_unavailable_reason": (
                "GraphRAG relationships need source and target columns"
            ),
        }
    predicted = {
        (gold_entities.resolve(row[source_col]), gold_entities.resolve(row[target_col]))
        for row in predicted_relationships.to_dict(orient="records")
    }
    gold: set[tuple[str, str]] = set()
    for row in gold_rows:
        source = _field(row, "source", "subject", "source_entity")
        target = _field(row, "target", "object", "target_entity")
        if source and target:
            gold.add((gold_entities.resolve(source), gold_entities.resolve(target)))
    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(gold - predicted)
    return {
        "relation_precision": tp / (tp + fp) if tp + fp else None,
        "relation_recall": tp / (tp + fn) if tp + fn else None,
        "relation_counts": {"true_positive": tp, "false_positive": fp, "false_negative": fn},
        "relation_gold_available": bool(gold),
        "relation_matching": "directed source-target pairs; GraphRAG 3.2 has no predicate column",
    }


def structural_metrics(graph: nx.Graph) -> dict[str, Any]:
    node_count, edge_count = graph.number_of_nodes(), graph.number_of_edges()
    components = list(nx.connected_components(graph)) if node_count else []
    largest = max((len(component) for component in components), default=0)
    degrees = [degree for _, degree in graph.degree()]
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "connected_components": len(components),
        "largest_connected_component_nodes": largest,
        "largest_connected_component_ratio": largest / node_count if node_count else 0.0,
        "isolated_nodes": sum(degree == 0 for degree in degrees),
        "average_degree": sum(degrees) / node_count if node_count else 0.0,
        "bridges": len(list(nx.bridges(graph))) if node_count else 0,
        "articulation_points": len(list(nx.articulation_points(graph))) if node_count else 0,
        "cycle_basis_count": len(nx.cycle_basis(graph)) if node_count else 0,
        "average_clustering": nx.average_clustering(graph) if node_count else 0.0,
        "density": nx.density(graph) if node_count > 1 else 0.0,
        "orphan_relationship_endpoints": 0,
    }


def build_graph(
    entities: pd.DataFrame, relationships: pd.DataFrame, gold: GoldEntities
) -> nx.Graph:
    graph = nx.Graph()
    for row in entities.to_dict(orient="records"):
        title = row.get("title")
        if title is None or not normalize_label(title):
            continue
        node = gold.resolve(title)
        graph.add_node(node, title=str(title), entity_type=str(row.get("type") or ""))
    entity_nodes = set(graph.nodes)
    orphan_endpoints = 0
    for row in relationships.to_dict(orient="records"):
        source, target = row.get("source"), row.get("target")
        if source is None or target is None:
            continue
        source_key, target_key = gold.resolve(source), gold.resolve(target)
        if source_key not in entity_nodes:
            orphan_endpoints += 1
        if target_key not in entity_nodes:
            orphan_endpoints += 1
        graph.add_edge(source_key, target_key)
    graph.graph["orphan_relationship_endpoints"] = orphan_endpoints
    return graph


def domain_coverage(graph_entities: pd.DataFrame, terms_path: Path) -> dict[str, Any]:
    if not terms_path.is_file():
        return {
            "domain_coverage": None,
            "matched_terms": [],
            "unmatched_terms": [],
            "term_count": None,
        }
    variants: list[tuple[str, list[str]]] = []
    for line in terms_path.read_text(encoding="utf-8").splitlines():
        values = [part.strip() for part in line.split("|") if part.strip()]
        if values:
            variants.append((values[0], values))
    if not variants:
        return {
            "domain_coverage": None,
            "matched_terms": [],
            "unmatched_terms": [],
            "term_count": 0,
        }
    corpus = "\n".join(
        f"{row.get('title') or ''} {row.get('description') or ''}"
        for row in graph_entities.to_dict(orient="records")
    )
    normalized_corpus = normalize_label(corpus)
    matched, unmatched = [], []
    for canonical, alternatives in variants:
        if any(normalize_label(alias) in normalized_corpus for alias in alternatives):
            matched.append(canonical)
        else:
            unmatched.append(canonical)
    return {
        "domain_coverage": len(matched) / len(variants),
        "matched_terms": matched,
        "unmatched_terms": unmatched,
        "term_count": len(variants),
    }


def _resolve_graph_node(graph: nx.Graph, gold: GoldEntities, label: str) -> str | None:
    if not label:
        return None
    key = gold.resolve(label)
    if key in graph:
        return key
    exact = normalize_label(label)
    return exact if exact in graph else None


def traversal_metrics(
    graph: nx.Graph,
    queries: list[dict[str, str]] | None,
    gold: GoldEntities,
) -> dict[str, Any]:
    if queries is None:
        return {
            "bfs_recall_at_2": None,
            "bfs_noise_ratio_at_2": None,
            "shortest_path_success_rate": None,
            "hit_rate_at_10": None,
            "mrr": None,
            "ndcg_at_10": None,
            "query_count": 0,
            "query_metrics": [],
            "unavailable_reason": "data/gold/traversal_queries.csv is missing",
        }
    query_metrics: list[dict[str, Any]] = []
    bfs_recalls: list[float] = []
    bfs_noise: list[float] = []
    path_success: list[float] = []
    hit_rate: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    for row in queries:
        query_id = _field(row, "query_id", "id")
        start_label = _field(row, "start_entity", "seed_entity", "start")
        target_label = _field(row, "target_entity", "target", "end_entity")
        start = _resolve_graph_node(graph, gold, start_label)
        target = _resolve_graph_node(graph, gold, target_label)
        expected_labels = split_values(_field(row, "expected_entities", "relevant_entities"))
        if not expected_labels and target_label:
            expected_labels = [target_label]
        expected = {gold.resolve(label) for label in expected_labels if label}
        if start:
            depths = nx.single_source_shortest_path_length(graph, start, cutoff=2)
            reached = [node for node, depth in depths.items() if 0 < depth <= 2]
            reached.sort(key=lambda node: (depths[node], node))
        else:
            depths, reached = {}, []
        recall = len(expected & set(reached)) / len(expected) if expected else None
        if recall is not None:
            bfs_recalls.append(recall)
        explicit_noise = {
            gold.resolve(value) for value in split_values(_field(row, "noise_entities"))
        }
        known_noise = explicit_noise | (gold.noise & set(reached))
        noise_ratio = (
            len(known_noise & set(reached)) / len(reached)
            if reached and (explicit_noise or gold.has_noise_labels)
            else None
        )
        if noise_ratio is not None:
            bfs_noise.append(noise_ratio)
        has_path = bool(start and target and nx.has_path(graph, start, target))
        if start_label and target_label:
            path_success.append(float(has_path))
        ranked = sorted(
            (node for node in depths if node != start),
            key=lambda node: (depths.get(node, math.inf), -graph.degree[node], node),
        )[:10]
        relevant_rank = [rank for rank, node in enumerate(ranked, start=1) if node in expected]
        if expected:
            hit_rate.append(float(bool(relevant_rank)))
            reciprocal_ranks.append(1 / relevant_rank[0] if relevant_rank else 0.0)
            dcg = sum(1 / math.log2(rank + 1) for rank in relevant_rank)
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(expected), 10) + 1))
            ndcgs.append(dcg / ideal if ideal else 0.0)
        query_metrics.append(
            {
                "query_id": query_id,
                "start_entity": start_label,
                "target_entity": target_label,
                "start_resolved": start is not None,
                "target_resolved": target is not None,
                "bfs_recall_at_2": recall,
                "bfs_reached_count_at_2": len(reached),
                "bfs_noise_ratio_at_2": noise_ratio,
                "shortest_path_success": has_path if start_label and target_label else None,
                "shortest_path_length": nx.shortest_path_length(graph, start, target)
                if has_path
                else None,
                "retrieval_top_10": ranked,
                "hit_rate_at_10": float(bool(relevant_rank)) if expected else None,
                "reciprocal_rank": 1 / relevant_rank[0]
                if relevant_rank
                else (0.0 if expected else None),
                "ndcg_at_10": (ndcgs[-1] if expected else None),
            }
        )

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        "bfs_recall_at_2": mean(bfs_recalls),
        "bfs_noise_ratio_at_2": mean(bfs_noise),
        "shortest_path_success_rate": mean(path_success),
        "hit_rate_at_10": mean(hit_rate),
        "mrr": mean(reciprocal_ranks),
        "ndcg_at_10": mean(ndcgs),
        "query_count": len(queries),
        "query_metrics": query_metrics,
        "retrieval_ranking": "BFS distance, then descending degree, then normalized entity name",
    }


def _compact(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def structure_integrity(
    arm_input: Path,
    mineru_root: Path,
    source_ids: list[str],
    *,
    kind: str,
    expected_tables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocks: list[tuple[str, int, str]] = []
    if kind == "table" and expected_tables:
        blocks = [
            (str(item["document"]), int(item["page"]), str(item["serialized"]))
            for item in expected_tables
            if item.get("document") and item.get("page") and item.get("serialized")
        ]
    for source_id in source_ids if not blocks else []:
        structured = mineru_root / source_id / "structured_content.json"
        if not structured.is_file():
            continue

        data = json.loads(structured.read_text(encoding="utf-8"))
        for page_number, page in enumerate(data.get("pages", []), start=1):
            for block in page.get("blocks", []):
                block_type = str(block.get("type", "")).casefold()
                if (kind == "formula" and block_type in {"equation", "formula"}) or (
                    kind == "table" and block_type == "table"
                ):
                    raw = block.get("content", "")
                    if raw:
                        blocks.append((source_id, page_number, str(raw)))
    if not blocks:
        return {
            f"{kind}_integrity": None,
            "preserved": 0,
            "expected": 0,
            "unavailable_reason": "no MinerU structures found",
        }
    preserved: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for source_id, page_number, raw in blocks:
        path = arm_input / f"{source_id}.txt"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if kind == "table" and expected_tables:
            intact = _compact(raw) in _compact(text)
        elif kind == "table":
            # Verify substantive cells across HTML and Markdown serialization.
            cells = re.findall(r"<(?:td|th)\b[^>]*>(.*?)</(?:td|th)>", raw, flags=re.I | re.S)
            visible = [html.unescape(re.sub(r"<[^>]+>", " ", cell)) for cell in cells]
            visible = [" ".join(value.split()) for value in visible if len(value.strip()) > 1]
            intact = _compact(raw) in _compact(text) or (
                bool(visible) and all(_compact(cell) in _compact(text) for cell in visible)
            )
        else:
            intact = _compact(raw) in _compact(text)
        entry = {"document": source_id, "page": page_number}
        (preserved if intact else missing).append(entry)
    return {
        f"{kind}_integrity": len(preserved) / len(blocks),
        "preserved": len(preserved),
        "expected": len(blocks),
        "preserved_structures": preserved,
        "missing_structures": missing,
        "scope": (
            "selected CLEAN table extraction or source MinerU structures preserved in the "
            "arm's GraphRAG input corpus"
        ),
    }
