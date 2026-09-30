# DIRTY vs CLEAN evaluation

## Metric scope

This report covers graph structure and formula/table preservation.

Graph topology is a simple undirected graph; duplicate and reverse relationships collapse into one edge. Formula and table integrity measure preservation from MinerU output into GraphRAG inputs, not graph extraction quality.

## Graph structure

| Metric | DIRTY | CLEAN | CLEAN − DIRTY |
| --- | ---: | ---: | ---: |
| Nodes | 1,592 | 1,831 | 239 |
| Unique undirected edges | 2,137 | 3,571 | 1,434 |
| Connected components | 199 | 84 | -115 |
| Largest component nodes | 1,315 | 1,702 | 387 |
| Largest component ratio | 82.6% | 93.0% | +10.4% |
| Isolated nodes | 172 | 64 | -108 |
| Average degree | 2.68 | 3.90 | 1.22 |
| Bridges | 711 | 548 | -163 |
| Articulation points | 379 | 318 | -61 |
| Cycle basis count | 744 | 1,824 | 1,080 |
| Average clustering | 0.068 | 0.221 | 0.152 |
| Density | 0.001687 | 0.002131 | 0.000444 |
| Orphan relationship endpoints | 0 | 0 | 0 |

## Formula and table preservation

| Check | DIRTY | CLEAN |
| --- | ---: | ---: |
| Formulas preserved | 14/14 (100%) | 14/14 (100%) |
| Tables preserved | 1/1 (100%) | 1/1 (100%) |

## SymPy equation validation

SymPy strict full-string parsing: **0/14 accepted**, **14 rejected**, **0 unavailable**. Each source below is a MinerU equation block; the DIRTY and CLEAN columns count exact occurrences of its original string in the prepared input text.

| MinerU equation | PDF page | SymPy parse | DIRTY copies | CLEAN copies |
| --- | ---: | --- | ---: | ---: |
| `stat3-F001` | 9 | Rejected | 1 | 1 |
| `tanaka1981-F001` | 5 | Rejected | 1 | 1 |
| `tanaka1981-F002` | 5 | Rejected | 1 | 1 |
| `tanaka1981-F003` | 6 | Rejected | 1 | 1 |
| `tanaka1981-F004` | 16 | Rejected | 1 | 1 |
| `tanaka1981-F005` | 16 | Rejected | 1 | 1 |
| `tanaka1981-F006` | 16 | Rejected | 1 | 1 |
| `tanaka1981-F007` | 17 | Rejected | 1 | 1 |
| `tanaka1981-F008` | 17 | Rejected | 1 | 1 |
| `tanaka1981-F009` | 17 | Rejected | 1 | 1 |
| `tanaka1981-F010` | 18 | Rejected | 1 | 1 |
| `tanaka1981-F011` | 18 | Rejected | 1 | 1 |
| `tanaka1981-F012` | 18 | Rejected | 1 | 1 |
| `tanaka1981-F013` | 18 | Rejected | 1 | 1 |

Parsing checks whether SymPy can consume the entire MinerU LaTeX string. Rejection may reflect OCR damage, layout markup, or LaTeX unsupported by SymPy; it does not by itself prove that the PDF equation is incorrect. Exact retention in both inputs does not verify mathematical fidelity to the PDFs. This check reads the existing prepared inputs; it does not rebuild either corpus.


## Reading the comparison

The CLEAN graph has more nodes and edges, fewer components and isolates, and a larger share of nodes in its largest component. Average degree and clustering are also higher. These structural differences do not establish semantic correctness.

Both arms preserved all formula and table structures counted by the checks: 14 formulas and 1 table in each arm.

Per-arm details are in `metrics_dirty.json` and `metrics_clean.json`. See [metrics.md](../docs/metrics.md) for definitions and limitations.

## GraphRAG question answering

The separate [factual query comparison](factual_query_comparison.md) reviews short source-checked answers from the DIRTY and CLEAN graphs.
