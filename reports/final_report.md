# Dirty vs clean evaluation

Metrics come from the per-arm JSON reports. Null values indicate unavailable gold data or missing judgments.

| Metric | Dirty | Clean | Clean − dirty |
| --- | ---: | ---: | ---: |
| articulation_points | 379 | 318 | -61 |
| average_clustering | 0.06841659714416623 | 0.22052015439059613 | 0.1521035572464299 |
| average_degree | 2.6846733668341707 | 3.900600764609503 | 1.2159273977753324 |
| bfs_noise_ratio_at_2 | None | None | None |
| bfs_recall_at_2 | None | None | None |
| bridges | 711 | 548 | -163 |
| connected_components | 199 | 84 | -115 |
| coreference_accuracy | None | None | None |
| cycle_basis_count | 744 | 1824 | 1080 |
| density | 0.0016874125498643436 | 0.002131475827655466 | 0.00044406327779112254 |
| domain_coverage | None | None | None |
| edge_count | 2137 | 3571 | 1434 |
| entity_gold_available | False | False | 0 |
| entity_metric_unavailable_reason | data/gold/entities.csv is missing or empty | data/gold/entities.csv is missing or empty | None |
| entity_precision | None | None | None |
| entity_recall | None | None | None |
| formula_integrity | 1.0 | 1.0 | 0.0 |
| hit_rate_at_10 | None | None | None |
| isolated_nodes | 172 | 64 | -108 |
| largest_connected_component_nodes | 1315 | 1702 | 387 |
| largest_connected_component_ratio | 0.8260050251256281 | 0.9295466957946478 | 0.10354167066901965 |
| mrr | None | None | None |
| ndcg_at_10 | None | None | None |
| node_count | 1592 | 1831 | 239 |
| noise_ratio | None | None | None |
| orphan_relationship_endpoints | 0 | 0 | 0 |
| query_count | 0 | 0 | 0 |
| relation_gold_available | False | False | 0 |
| relation_precision | None | None | None |
| relation_recall | None | None | None |
| shortest_path_success_rate | None | None | None |
| table_integrity | 1.0 | 1.0 | 0.0 |
| term_count | None | None | None |
| unavailable_reason | data/gold/traversal_queries.csv is missing | data/gold/traversal_queries.csv is missing | None |

## Indexing status

The latest DIRTY and CLEAN GraphRAG indexing runs both completed, including `generate_text_embeddings`. The local embedding endpoint passed a 5,602-token test before indexing. Shared GraphRAG settings were unchanged between arms. See `reports/indexing_status.json` for run status.
