# Graph evaluation and metrics

This document describes the repository's **current metric implementation** and the evaluation requested by `AGENTS.md` and `PROJECT_SPEC.md`. At present, there is no graph evaluation pipeline: `src/metallab/evaluation/__init__.py` is a placeholder, and `metallab evaluate --arm dirty`, `metallab evaluate --arm clean`, and `metallab compare` exit with an unimplemented error. The output files under `reports/` specified in `PROJECT_SPEC.md` are planned, not produced by these commands.

## What the code measures today

`scripts/run_pair_index.py` runs the dirty and clean GraphRAG indexes in sequence after validating that their shared settings match. For each arm, it reads **Parquet metadata row counts** from the GraphRAG output directory:

| Report field | GraphRAG file | Meaning |
| --- | --- | --- |
| `chunk_count` | `text_units.parquet` | Number of output text-unit rows. |
| `output_document_count` | `documents.parquet` | Number of output document rows. |
| `entity_count` | `entities.parquet` | Number of entity rows. |
| `relationship_count` | `relationships.parquet` | Number of relationship rows. |

The script writes these fields, run status, timestamps, input hashes, model names, settings and prompt hashes, and the GraphRAG exit code to `reports/run_dirty.json` and `reports/run_clean.json`. It writes indexing logs to `reports/index_dirty.log` and `reports/index_clean.log`. `output_count()` returns `null` in the JSON when a Parquet file is missing; a missing entity or relationship file causes the run to be marked failed. It checks only row counts, not the content or quality of graph records. These counts are **not yet** NetworkX node/edge counts: no code loads the rows, resolves duplicate entities, selects graph direction, or handles parallel relationships.

GraphRAG workspace settings enable GraphML and raw graph snapshots, but the repository does not currently analyze them. At inspection, this checkout contained dirty-arm Parquet outputs and `data/dirty/graphrag/output/graph.graphml`, but no clean-arm GraphRAG output files. `reports/run_dirty.json` said `running` and `reports/run_clean.json` said `pending`; both had null count fields. Those run reports are indexing state, not completed metric reports. The existence of the dirty graph does not mean its evaluation has run.

## Planned evaluation inputs and comparison

The project instructions call for loading each arm's `entities.parquet` and `relationships.parquet`, converting the results to NetworkX graphs, and comparing dirty with clean. Both source PDFs must contribute to one graph in each arm. The same entity types, prompts, models, chunking, extraction settings, and source PDFs must be used on both sides. The intended comparison is sensitive to preprocessing; changes in shared GraphRAG settings would invalidate it.

The following metric definitions are **proposed interpretations of the requirements**, not formulas implemented by the current repository. Before calculating them, the evaluator must define how GraphRAG entity IDs/names are canonicalized, how duplicate and parallel relationships are represented, whether edge direction is retained, and how source-document provenance is assigned. These choices affect almost every result below and must be identical for both arms.

## Graph structure and importance

The requested structural metrics in `AGENTS.md` are:

| Metric | Intended question or usual definition |
| --- | --- |
| Node and edge counts | How many distinct entities and graph links exist after the chosen canonicalization and edge policy? |
| Density | What fraction of possible links exist? For a simple undirected graph, `2E / (V(V-1))` when `V > 1`. |
| Connected components | How many disconnected groups are there, and how large is the largest? Usually computed on an undirected view. |
| Isolated nodes | How many nodes have degree zero? |
| Degree distribution; average, median, maximum degree | How many neighbors or incident edges does each node have? The treatment of parallel edges must be fixed. |
| Bridges and articulation points | Which edges or nodes disconnect an undirected component when removed? |
| Cycle basis | Which independent cycles are found under a specified undirected graph and traversal order? |
| Cyclomatic number | Number of independent cycles; for an undirected graph, `E - V + C`, where `C` is the component count. |
| Clustering coefficient | How often a node's neighbors are linked to one another? Specify whether the reported value is per-node or averaged. |
| Average shortest path in largest connected component | Typical path length among nodes in that component. A singleton needs an explicit convention. |
| Degree centrality, betweenness centrality, PageRank | Which entities are most connected, lie on many shortest paths, or rank highly by link structure? Direction, weights, normalization, and PageRank parameters must be fixed. |

NetworkX is the specified graph-analysis library. Raw graph size or density alone cannot establish extraction quality: extra noisy entities can increase counts and distort connectivity.

## Gold-label and content metrics

The project expects manually maintained `data/gold/entities.csv`, `relations.csv`, `coreference.csv`, `domain_terms.txt`, and `traversal_queries.csv`. They are not present in this checkout. No labels should be invented to make a metric computable. The requested metrics are:

| Metric | Data and decision needed |
| --- | --- |
| Entity precision and recall | Match predicted entities to reviewed gold entities. Precision is `TP / (TP + FP)`; recall is `TP / (TP + FN)`. Define aliases, entity types, and span/name matching first. |
| Relation precision and recall | Match predicted source–relation–target triples to gold relations. Use one consistent policy for relation labels, direction, aliases, and duplicate triples. The same precision/recall formulas apply. |
| Coreference accuracy | Compare extracted entity merges or mention-to-entity links with reviewed coreference labels. Define the unit of scoring and treatment of unmatched mentions. |
| Noise ratio | Quantify predicted entities and/or relations judged irrelevant or incorrect by an explicit gold or review policy. The denominator and what qualifies as noise are not yet specified. |
| Domain coverage | Check whether reviewed domain terms or concepts are represented in the graph. Define synonym matching and the denominator from `domain_terms.txt`. |
| Formula and table integrity | Compare source MinerU/PDF structures with the prepared text and, if measuring graph preservation, with extracted graph evidence. Define exact-match versus semantic scoring and the expected structure set. |
| Numeric-value and unit integrity | Requested by `PROJECT_SPEC.md`; compare original values/units with retained or graph-extracted evidence using reviewed matching rules. |

The clean preprocessing report's `integrity: "passed"` is **not** a formula-integrity, table-integrity, or graph-quality score. It checks for nonempty output, restored protected structures, and preserved source numeric tokens. It does not evaluate GraphRAG extraction. When the gold files are absent, gold-dependent scores should remain unavailable rather than be reported as zero.

## Traversal, retrieval, and cross-document questions

The requested traversal experiments are BFS to depths 1, 2, and 3; DFS; shortest path; and bidirectional shortest path. Queries should come from the manually maintained traversal file. For each query, the evaluator needs to record relevant and noisy nodes reached, expected entities reached, whether the expected path exists, and path length. Traversal order and depth conventions must be fixed so the two arms are comparable. `PROJECT_SPEC.md` also asks for runtime, but the project instructions prioritize semantic usefulness.

Retrieval metrics `HitRate@10`, MRR, and `NDCG@10` require a ranked result list and judged relevant results per query. HitRate@10 asks whether at least one relevant result appears in the first ten; MRR uses the reciprocal rank of the first relevant result; NDCG@10 discounts relevance by rank and normally supports graded relevance. The repository has no retrieval evaluator or relevance judgments yet, so none of these can currently be calculated.

Because both PDFs feed one graph per arm, the project also requests entities appearing in both documents, document-specific entities, cross-document edges and their ratio, and paths between concepts originating in different documents. This needs document provenance on entities and relationships or reliable links back to text units/documents. The evaluator must state how shared entities are assigned to documents and what counts as a cross-document edge. The current row-count script does none of this.

## Current limitations and code map

- `src/metallab/cli.py`: `evaluate` and `compare` are reserved commands that exit with code 2.
- `src/metallab/evaluation/__init__.py`: placeholder; no evaluation functions.
- `scripts/run_pair_index.py`: indexing and Parquet row-count reporting only.
- `src/metallab/graph/workspace.py`: shared settings validation and GraphRAG input/output locations.
- `AGENTS.md`: required metrics, traversal experiments, cross-document analysis, and gold-file names.
- `PROJECT_SPEC.md`: additional preservation metrics and intended report filenames.

Consequently, the current experiment can report how many rows GraphRAG wrote during indexing, but it cannot yet report graph topology, semantic extraction quality, traversal quality, retrieval effectiveness, or dirty-versus-clean metric deltas.
