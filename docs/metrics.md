# Graph and retrieval evaluation

The evaluator reads Microsoft GraphRAG `entities.parquet` and
`relationships.parquet` from one arm, computes the requested graph and judged
metrics, and writes JSON plus a GraphML snapshot. It does not start GraphRAG or
call either model API.

```bash
uv run python -m metallab evaluate --arm dirty
uv run python -m metallab evaluate --arm clean
uv run python -m metallab compare
```

Each arm needs an indexed workspace at
`data/<arm>/graphrag/output/`. The evaluator writes
`reports/metrics_<arm>.json` and `reports/<arm>_graph.graphml`. Once both arm
reports exist, `compare` writes `reports/comparison.csv`,
`reports/graph_metrics.csv`, `reports/traversal_metrics.csv`, and
`reports/final_report.md`. A missing GraphRAG artifact is an error. Gold-based
metrics remain JSON `null` when their reviewed labels or queries are missing;
missing labels are never treated as zero scores.

## Metric definitions

### Entity and relation quality

Gold files are maintained by hand under `data/gold/`; no labels are generated
from the graph. UTF-8 CSV headers are case-insensitive. Alias and list fields
use `|` or `;` separators.

| File | Required fields | Optional fields | Meaning |
| --- | --- | --- | --- |
| `entities.csv` | One of `entity`, `canonical_entity`, `name`, or `title` | `aliases`, `is_noise` | Positive gold entities and known aliases. Rows marked `is_noise=true` are negative/noise labels. |
| `relations.csv` | `source`, `target` | `relation` or `predicate` for human reference | Directed gold links. |
| `coreference.csv` | `mention`, `canonical_entity` | — | Reviewed mention-to-cluster labels. |
| `domain_terms.txt` | One concept per line | Add `|alias` variants on the same line | Reviewed domain concepts for coverage. |
| `traversal_queries.csv` | `start_entity`, `target_entity` | `query_id`, `expected_entities`, `relevant_entities`, `noise_entities` | Seeds, expected reachable concepts, and reviewed noisy concepts. Lists are pipe- or semicolon-separated. |

Entity matching uses Unicode NFC, case folding, whitespace collapse, and explicit
aliases from the gold file. It does not stem, translate, or infer synonyms.

- **Entity Precision** = matched predicted entities / predicted entities.
- **Entity Recall** = matched gold entities / positive gold entities.
- **Relation Precision/Recall** use directed `(source, target)` pairs. GraphRAG
  3.2's `relationships.parquet` has no predicate/type field, so the evaluator
  cannot reliably score relation labels from its prose descriptions.
- **Noise Ratio** = predicted entities not matched to a positive gold entity /
  predicted entities. Treat this as a meaningful noise estimate only when the
  gold entity list is complete for the corpus. Explicit `is_noise` rows are
  counted as non-matches.
- **Coreference Accuracy** is pairwise cluster accuracy over pairs of reviewed
  mentions. Predicted clusters are inferred from GraphRAG `raw_entities` names
  resolved against final entity names and the reviewed aliases. The report also
  gives mention-resolution coverage and pair count.
- **Domain Coverage** is the fraction of reviewed domain-term groups whose
  canonical term or listed alias appears in a GraphRAG entity title or
  description. It is literal phrase matching after NFC/casefold/whitespace
  normalization.

Scores with no predicted or gold denominator are `null`, not 0. These are
entity-level micro counts over the arm's graph.

### Formula and table integrity

Formula integrity compares each formula block in saved MinerU
`structured_content.json` with that document's prepared arm input after NFC,
case folding, and whitespace normalization. For DIRTY, table integrity first
checks the MinerU table block, then falls back to checking whether all substantive
HTML cell contents appear in the input. For CLEAN, it checks the selected table output
recorded by preprocessing (Camelot when accepted, otherwise the documented
MinerU fallback) against the final input using the same normalized substring
comparison. The JSON contains preserved/missing
counts and document/page locations. A value of `null` means no structures of
that kind were found. These metrics assess preservation into GraphRAG input;
they do not claim GraphRAG extracted the structures as graph entities or
relations.

### Graph structure

The graph is a simple undirected NetworkX view made from final entity titles and
relationship endpoints. Duplicate and reverse relationships collapse into one
edge for topology, while relation precision/recall remains directed. Any
relationship endpoint missing from `entities.parquet` is included as a node and
counted in `orphan_relationship_endpoints`.

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

Density is also reported as a diagnostic. All topology metrics are computed on
the same undirected simple graph so arm-to-arm counts are comparable.

### Traversal and ranked neighborhood metrics

Queries come from `traversal_queries.csv`. BFS depth 2 counts edges from the
start node and excludes the start itself. BFS Recall@2 is the mean per-query
fraction of all listed expected entities reached; expected entities absent from
the graph remain in the denominator. BFS Noise Ratio@2 is noisy reached nodes /
all reached nodes, averaged only where noise judgments exist through
`noise_entities` or `entities.csv:is_noise`.

Shortest Path Success Rate is the fraction of query rows with both endpoints
specified for which the endpoints resolve and a path exists. Unresolved
endpoints count as failures. Per-query results and path lengths are stored in
the JSON report.

Hit Rate@10, MRR, and NDCG@10 use deterministic graph-neighborhood rankings:
reachable candidates within two hops sort by increasing BFS distance,
decreasing degree, then normalized name. The relevance set is `expected_entities` (or `target_entity`
when no expected list is supplied). NDCG uses binary relevance. These scores
are retrieval proxies over graph neighborhoods, **not** Microsoft GraphRAG
LLM/local-search results. A future GraphRAG query benchmark should provide its
own ranked results and judgments.

## Current checkout and limitations

The DIRTY arm has indexed GraphRAG artifacts, while the CLEAN GraphRAG output
is absent. An existing `reports/metrics_dirty.json` is older than the current
DIRTY Parquet artifacts; rerun `evaluate --arm dirty` before using its graph
metrics. The gold directory currently has no reviewed labels or traversal
queries, so the corresponding semantic, domain, and traversal scores are `null`.
`evaluate --arm clean` requires indexing that arm first.

There is no manual gold annotation in this repository yet. Create gold labels
from document review before interpreting quality scores. Do not use generated
entity descriptions as ground truth.
