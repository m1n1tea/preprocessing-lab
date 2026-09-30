# Graph structure and preservation evaluation

The evaluator reads Microsoft GraphRAG `entities.parquet` and
`relationships.parquet` from one arm and writes graph topology and structure
preservation results to JSON plus a GraphML snapshot. It does not start
GraphRAG or call either model API.

```bash
uv run python -m metallab evaluate --arm dirty
uv run python -m metallab evaluate --arm clean
uv run python -m metallab compare
```

Each arm needs an indexed workspace at
`data/<arm>/graphrag/output/`. The evaluator writes
`reports/metrics_<arm>.json` and `reports/<arm>_graph.graphml`. Once both arm
reports exist, `compare` writes paired CSV and Markdown summaries, including
`reports/graph_metrics.csv` and `reports/final_report.md`. A missing GraphRAG
artifact is an error.

## Graph structure

The graph is a simple undirected NetworkX view made from final entity titles and
relationship endpoints. Duplicate and reverse relationships collapse into one
edge for topology. Any relationship endpoint missing from `entities.parquet` is
included as a node and counted in `orphan_relationship_endpoints`.

| Metric | Definition |
| --- | --- |
| Node Count | Unique nodes in the topology view, including orphan endpoints. |
| Edge Count | Unique undirected edges after duplicate/reverse edges collapse. |
| Connected Components | Number of connected components in that view. |
| Largest Connected Component Ratio | Nodes in the largest component / all nodes; 0 for an empty graph. |
| Isolated Nodes | Nodes with degree zero. |
| Average Degree | Mean degree across all nodes, including isolates. |
| Bridges | Edges whose removal increases the component count. |
| Articulation Points | Nodes whose removal increases the component count. |
| Cycle Basis Count | Number of cycles in NetworkX's cycle basis across the graph. |
| Average Clustering | NetworkX mean local clustering coefficient. |

Density is also reported as a diagnostic. All topology metrics use the same
undirected simple graph so arm-to-arm counts are comparable.

## Formula and table integrity

Formula integrity compares each formula block in saved MinerU
`structured_content.json` with that document's prepared arm input after NFC,
case folding, and whitespace normalization. For DIRTY, table integrity first
checks the MinerU table block, then falls back to checking whether all
substantive HTML cell contents appear in the input. For CLEAN, it checks the
selected table output recorded by preprocessing (Camelot when accepted,
otherwise the documented MinerU fallback) against the final input using the
same normalized substring comparison. The JSON contains preserved/missing
counts and document/page locations. A value of `null` means no structures of
that kind were found. These metrics assess preservation into GraphRAG input;
they do not claim GraphRAG extracted the structures as graph entities or
relations.
