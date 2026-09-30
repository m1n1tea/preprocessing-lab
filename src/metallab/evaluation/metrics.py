"""Graph topology and structure-preservation metrics."""

from __future__ import annotations

import html
import json
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


def build_graph(entities: pd.DataFrame, relationships: pd.DataFrame) -> nx.Graph:
    graph = nx.Graph()
    for row in entities.to_dict(orient="records"):
        title = row.get("title")
        if title is None or not normalize_label(title):
            continue
        node = normalize_label(title)
        graph.add_node(node, title=str(title), entity_type=str(row.get("type") or ""))
    entity_nodes = set(graph.nodes)
    orphan_endpoints = 0
    for row in relationships.to_dict(orient="records"):
        source, target = row.get("source"), row.get("target")
        if source is None or target is None:
            continue
        source_key, target_key = normalize_label(source), normalize_label(target)
        if source_key not in entity_nodes:
            orphan_endpoints += 1
        if target_key not in entity_nodes:
            orphan_endpoints += 1
        graph.add_edge(source_key, target_key)
    graph.graph["orphan_relationship_endpoints"] = orphan_endpoints
    return graph


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
