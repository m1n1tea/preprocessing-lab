# Global versus DRIFT query speed

Measured on three short factual questions (`f01`–`f03`) in both indexed
workspaces. Both methods used the same question and response instruction for
each pair. Queries ran with up to two concurrent GraphRAG processes. The
query-only settings used bounded DRIFT search (`drift_k_followups: 4`,
`n_depth: 1`); indexed workspaces were unchanged. Durations are wall-clock
time per query, including GraphRAG startup and API calls.

| Question | Corpus | DRIFT (s) | Global (s) | DRIFT / global |
| --- | --- | ---: | ---: | ---: |
| f01: rolling temperature | dirty | 143.92 | 22.22 | 6.48× |
| f01: rolling temperature | clean | 144.18 | 46.14 | 3.12× |
| f02: cooling rate | dirty | 119.10 | 20.73 | 5.75× |
| f02: cooling rate | clean | 360.45 | 20.56 | 17.53× |
| f03: rolling-rate increase | dirty | 141.94 | 25.88 | 5.48× |
| f03: rolling-rate increase | clean | 143.78 | 22.19 | 6.48× |

Median: **143.85 s for DRIFT** and **22.21 s for global** (about **6.5×**
faster by median duration). Global was faster in all six pairs. Both methods
returned the same substantive values: 730–800 °C, 10–30 °C/s, and up to 20%.

This is a small sample with one run per pairing; API load and model latency
can change the exact timings. Global cited community reports in these
answers, while DRIFT often cited source text units directly. Answer agreement
here does not establish equal accuracy on more detailed questions.

Raw responses and timings: [`f01`–`f03` JSON files](factual_query_answers/).
