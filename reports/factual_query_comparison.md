# Short factual questions: local and global search

Ten reviewed questions were sent to the DIRTY and CLEAN GraphRAG indexes in
`local` and `global` modes. Each answer was limited to a short fact with a
citation. The question list, expected source facts, and PDF page references are
in [factual_query_questions.csv](factual_query_questions.csv). The
[manifest](factual_query_answers/manifest.json) records the GraphRAG version,
models, configuration hashes, question hash, and all 40 runs. Raw answers and
individual timings are in [factual_query_answers/](factual_query_answers/).

All 40 query processes succeeded. The following review compares answer content
with the cited source facts; it is not a statistical accuracy estimate.

| ID | Source fact | Comparison across DIRTY/CLEAN and local/global |
| --- | --- | --- |
| f01 | 730–800 °C | All four agree. |
| f02 | 10–30 °C/s | All four agree. |
| f03 | Up to 20% | All four agree. |
| f04 | About 300 s for the existing process | All four give 300 s. CLEAN global also mentions the distinct revised 150–200 s process. |
| f05 | 5 passes before cooling, 3 after | All four agree. |
| f06 | Stage 2 | All four agree. |
| f07 | Deformation bands | All four agree. |
| f08 | Austenite grain interior | All four describe an intragranular site. DIRTY global names deformation bands within grains, less directly than the others. |
| f09 | Niobium (Nb) | All four agree. |
| f10 | `σ_y = σ_0 + k_y d^(-1/2)` | All four give the Hall–Petch relation. DIRTY global changes the source symbols to `K_y D^(-1/2)`; the other three preserve `k_y d^(-1/2)`. |

The f10 symbol change is a **formal fidelity issue**: letter case can denote a
different variable in an equation. Both corpus inputs preserve the original
`k_y d^(-1/2)` notation, so this observed change is in the DIRTY global answer,
not a demonstrated loss during PDF extraction or preprocessing. One response
per case cannot establish whether this is systematic.

Median query time across the 20 runs per method was **12.65 s for local** and
**28.62 s for global**. Global is slower than local on this factual set, while
the separate [global versus DRIFT benchmark](search_method_benchmark.md) found
global faster than DRIFT on six matched runs. These timings include GraphRAG
startup and API latency.

The short answers mostly agree. The existing
[formal follow-up questions](formal_followup_candidates.csv) test longer
process reconstruction, arithmetic, exact formula terms, and cross-document
reasoning. They have not been run.
