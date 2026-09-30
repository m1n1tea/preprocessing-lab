# Metallurgical GraphRAG preprocessing experiment

This repository compares two GraphRAG graphs built from the same metallurgical
papers, `stat3.pdf` and `tanaka1981.pdf`. Each graph contains **both** documents.
DIRTY uses MinerU Markdown with no semantic cleanup; CLEAN uses MinerU structured
content and the preprocessing pipeline. Both indexes and their evaluations have
been produced. The intended experimental difference is preprocessing; the
GraphRAG models, prompts, entity types, chunking, and extraction settings are
shared. DIRTY consumes MinerU Markdown while CLEAN consumes structured JSON, so
the comparison also includes that serialization difference. The figures below
describe the saved run, not guaranteed results of a new run.

## What happens to the documents

| Step | DIRTY | CLEAN | Main tools |
| --- | --- | --- | --- |
| PDF extraction | MinerU saves Markdown, structured JSON, page/block information, formulas, images, and tables under separate `data/mineru/<document>/` directories. | Same extraction artifacts and settings. | MinerU 4.0.8; `pypdf` validates source PDFs and page counts. |
| Corpus input | Copies each `markdown.md` byte-for-byte into `data/dirty/input/<document>.txt`. No OCR repair, dehyphenation, header removal, or unit changes. | Reads `structured_content.json` and writes one normalized text file per document in `data/clean/input/`. | Python UTF-8 serialization; `regex`, `ftfy`, Camelot, pandas, Pint, optional SymPy. |
| Graph construction | Ingests both text files into one DIRTY GraphRAG workspace. | Ingests both text files into one CLEAN GraphRAG workspace. | Microsoft GraphRAG 3.2.0, remote generation API, local vLLM embeddings, LanceDB. |
| Evaluation | Reads saved Parquet and question results. | Same evaluation procedure. | pandas, NetworkX. |

MinerU uses the Basic tier with automatic OCR, image analysis enabled, and
all PDF pages. CLEAN then applies these guarded stages in order:

1. Identify MinerU blocks; protect formulas, table content, abbreviations, and number/unit spans. For table candidates, Camelot lattice rereads the PDF page, checks extraction quality, and falls back to MinerU if needed. The accepted cells receive the applicable text cleanup before table serialization.
2. Normalize Unicode to NFC; accept an `ftfy` repair only if technical-token checks pass. Remove control characters and normalize line endings, whitespace, and blank lines.
3. Detect recurring headers and footers at page edges, remove standalone page numbers, and keep unique page-edge content.
4. Join conservative PDF line-break hyphenations while preserving technical symbols and real compound words.
5. Flag suspicious OCR tokens for review. Automatic correction requires an explicitly reviewed token and context rule; the current correction list is empty.
6. Recognize numbers and units with Pint, append SI forms while retaining the source numbers and notation, annotate valid dates, and expand configured abbreviations at first use. Table column headings can supply missing unit context.
7. Restore protected content, preserve the selected table and original formula strings, and validate marker, numeric-token, and output integrity. Optional SymPy checks whether each complete MinerU LaTeX formula parses; parsing is not a check against the printed PDF.

The text is never globally lowercased, stripped of stopwords, or aggressively
lemmatized. [The pipeline description](docs/preprocessing_pipeline.md) gives
the exact rules; [the audit JSONL](data/clean/audit/) records each applied text
change with before/after text and a page/block reference.

### Observed preprocessing changes

Counts below come from the current [stat3](reports/preprocessing/stat3.md) and
[tanaka1981](reports/preprocessing/tanaka1981.md) preprocessing reports. They
are stage counts, not independent error counts; recognized quantities can
outnumber text edits.

| Measure | `stat3` | `tanaka1981` |
| --- | ---: | ---: |
| Source PDF pages | 10 | 28 |
| Characters, structured input → CLEAN output | 21,573 → 22,146 | 99,662 → 98,579 |
| `hyphenation_repair` | **97** | **0** |
| Repeated headers / footers removed | 0 / 0 | 27 / 28 |
| Page numbers removed | 10 | 28 |
| Whitespace repairs | 5 | 0 |
| Unit annotations applied | 69 | 16 |
| OCR suspects flagged / automatic corrections | 1 / 0 | 13 / 0 |
| Abbreviation expansions | 2 | 0 |
| Formula blocks protected and restored | 1 | 13 |
| Accepted Camelot tables | 1 | 0 |

Examples from the current outputs:

| Before | After in CLEAN | Reason |
| --- | --- | --- |
| `ох- лаждение` | `охлаждение` | PDF line-break hyphenation repair. |
| `КП` on first use | `КП [контролируемая прокатка]` | Keep the abbreviation and add its configured meaning. |
| `20%` | `20% [SI: 0.2]` | Keep the reported value and add a Pint-derived fraction. |
| Table temperature `1120–1150`, under a Celsius heading | `1120–1150 [SI: 1393.15–1423.15 K]` | Use table-column context; retain the Celsius numbers. |
| Table heading `0С` | `0С [unit: °C]` | Annotate the recognized Celsius glyph without deleting its source form. |

The accepted `stat3` table has 7 rows and 13 columns. Both corpus inputs
preserve all 14 MinerU formula blocks and the one evaluated table structure.
Strict SymPy parsing accepted **0/14** original formula strings; all remain in
the inputs. A parse rejection may reflect MinerU LaTeX syntax or unsupported
layout and does not by itself prove a mathematical error.

### External libraries and services

MinerU parses the PDFs; `pypdf` validates them. CLEAN uses `regex` and `ftfy`
for guarded text repair, Camelot for table extraction, pandas for table and
Parquet handling, Pint for unit conversions, and optional SymPy for LaTeX
parsing. Microsoft GraphRAG constructs the graphs; pandas loads its Parquet
outputs and NetworkX calculates topology and traversal metrics. PyYAML and
Pydantic load and validate configuration. A remote OpenAI-compatible service
runs generation; a local vLLM OpenAI-compatible service runs embeddings.

## Graph generation settings

The completed index logs record **`deepseek-v4.1-flash`** for generation and
**`qwen3-embedding-4b`** (Qwen/Qwen3-Embedding-4B) for embeddings in both
workspaces. Generation uses the configured remote OpenAI-compatible API;
embeddings use local vLLM at `http://127.0.0.1:8000/v1` with 2,560-dimensional
vectors. Credentials and the generation endpoint come from environment
variables, not the README. The two workspaces share the
[GraphRAG template](configs/graphrag/settings.template.yaml) and
[prompts](configs/graphrag/prompts/); only their input/output locations differ.

| Setting | Shared value in the saved indexes |
| --- | --- |
| Documents / final text chunks | 2 / 50 DIRTY; 2 / 47 CLEAN |
| Chunking | 800 tokens, overlap 120, `o200k_base` tokenizer |
| Graph extraction | One gleaning; claims extraction disabled |
| Community clustering | Maximum cluster size 10, `use_lcc: false`, seed 42 |
| Community reports | Maximum length 1,000; maximum input length 8,000 |
| Vector store / snapshots | LanceDB; GraphML and raw-graph snapshots enabled |

The 16 shared [entity types](configs/graphrag/entity_types.yaml) are
`PROCESS`, `PROCESS_ROUTE`, `PROCESS_STAGE`, `COOLING_METHOD`, `EQUIPMENT`,
`STEEL_GRADE`, `ALLOY_FAMILY`, `PRODUCT_FORM`, `CHEMICAL_ELEMENT`,
`PRECIPITATE`, `PHASE`, `MICROSTRUCTURE`, `PROPERTY`, `PROCESS_CONDITION`,
`MODEL`, and `FORMULA`.

## Evaluation and question tests

The evaluator makes a **simple undirected** NetworkX graph from
`entities.parquet` and `relationships.parquet`; duplicate and reverse edges
collapse. It measures node/edge counts, connected components, largest-component
ratio, isolates, average degree, density, bridges, articulation points, cycle
basis count, and average clustering. The current
[graph metrics](reports/graph_metrics.csv) include:

| Metric | DIRTY | CLEAN |
| --- | ---: | ---: |
| Nodes / unique edges | 1,592 / 2,137 | 1,831 / 3,571 |
| Connected components / isolated nodes | 199 / 172 | 84 / 64 |
| Largest-component ratio | 82.6% | 93.0% |
| Average degree / average clustering | 2.68 / 0.068 | 3.90 / 0.221 |
| Bridges / articulation points | 711 / 379 | 548 / 318 |
| Cycle basis count | 744 | 1,824 |

Formula and table integrity check preservation into corpus text; they do not
score extraction into the graph. [Metric definitions](docs/metrics.md) explain
the topology and preservation measures.

A separate test sent these **ten short, source-checked questions** to both
graphs in `local` and `global` search modes (40 successful runs). The exact
prompts, source pages, and responses are in
[the question CSV](reports/factual_query_questions.csv) and
[answer comparison](reports/factual_query_comparison.md).

| ID | Concrete question | Source fact to check |
| --- | --- | --- |
| f01 | At Azovstal mill 3600, what high-temperature controlled-rolling range is reported? | 730–800 °C |
| f02 | What accelerated-cooling rate after deformation is reported for thick plate? | 10–30 °C/s |
| f03 | What maximum rolling-rate increase is reported for high-temperature rolling with accelerated cooling? | Up to 20% |
| f04 | Under existing low-temperature controlled rolling at mill 3600, how long is the air-cooling hold for a roughly 50 mm slab? | About 300 s |
| f05 | In the КП+УО+КП route, how many finishing passes occur before and after accelerated cooling? | 5 before, 3 after |
| f06 | Which controlled-rolling stage uses the non-recrystallization region? | Stage 2 |
| f07 | What feature divides unrecrystallized austenite grains during controlled rolling? | Deformation bands |
| f08 | Besides austenite grain boundaries, where does ferrite nucleate in controlled-rolled steel? | Austenite grain interior |
| f09 | Which element retards austenite recrystallization? | Niobium (Nb) |
| f10 | What is Eq. (8) for the Hall–Petch yield-stress relation? | `σ_y = σ_0 + k_y d^(-1/2)` |

All four answer sets returned these substantive facts. DIRTY global changed
the case of `k_y d` to `K_y D` in f10, a formal notation error; the other
three answers preserved the source symbols. Median query time was 12.65 s for
local and 28.62 s for global. An earlier six-run
[benchmark](reports/search_method_benchmark.md) found global faster than
DRIFT. These results use one response per case and do not establish a
statistical accuracy difference. More complex questions are drafted in
[formal_followup_candidates.csv](reports/formal_followup_candidates.csv).

## Setup on Ubuntu

Install uv if needed, then run:

    uv python install 3.12
    uv sync --locked --extra formulas
    uv run python -m metallab doctor

MinerU 4.0.8 is pinned in pyproject.toml and uv.lock. The first extraction run
may download MinerU models. The shared parser settings are in
configs/mineru.yaml: Basic tier, automatic OCR, image analysis enabled, and all
pages. MinerU Basic can run without a local VLM.

## Extract both PDFs

From the repository root:

    uv run python -m metallab extraction run
    uv run python -m metallab extraction validate

The installed console script is equivalent:

    uv run metallab extraction run

The older shorthand, uv run metallab extract, also runs extraction. The run
checks that both source PDFs exist before parsing either one. It validates
non-empty extracted text and complete page coverage before publishing each
output directory. A completed directory with the same PDF hash, MinerU
version, and settings is validated and reused on later runs. If those inputs
change, move the old directory aside before rerunning. If extraction fails,
partial files remain in a hidden staging directory under data/mineru/ for
inspection.

MinerU's saved output is kept separately:

    data/mineru/stat3/
      markdown.md
      middle_json.json
      structured_content.json
      model_output.json (when available)
      images/ (when available)
      manifest.json
    data/mineru/tanaka1981/
      same artifact names

The JSON contains page indices, block types, tables, formulas, metadata, and
other content exposed by MinerU. The manifest records source identity and hash,
page count, MinerU version, parser settings, artifact inventory, and basic
preservation counts. These directories are ignored by Git; the source PDFs
remain in data/source/.

MinerU can classify body text as page furniture. In the current Tanaka Basic
output, references 138-146 on its final page are retained as header blocks in
the structured JSON but omitted from markdown.md. Review the structured
content and images before using the Markdown as GraphRAG input. No text cleanup
or correction occurs in the extraction stage.

## Build the dirty corpus

    uv run python -m metallab prepare --arm dirty

This validates both MinerU outputs, then copies markdown.md bytes exactly to

data/dirty/input/stat3.txt and data/dirty/input/tanaka1981.txt. The files are
UTF-8 checked and written deterministically. The stage does not remove headers,
repair OCR or formulas, join hyphenated words, or normalize abbreviations,
tables, or units. It logs each document's character and byte count and a total.
Rerunning with unchanged inputs leaves identical output files in place. The
two files are ingested together in one dirty GraphRAG workspace.

The current Tanaka Markdown omits final-page references 138-146 because MinerU
classified them as headers; the dirty stage intentionally preserves that output
as-is. Their text remains in MinerU's structured JSON for later analysis.

## Build the clean corpus

    uv run python -m metallab prepare --arm clean

This validates both MinerU outputs and reads each `structured_content.json` rather
than the Markdown. It writes `data/clean/input/stat3.txt` and
`data/clean/input/tanaka1981.txt` for the shared clean GraphRAG workspace.
Every run writes `data/clean/reports/<source>.json` and
`data/clean/audit/<source>.jsonl`. The JSON report records stage counts, table
and formula validation, quantities, OCR review candidates, and final integrity
status. The JSONL audit records each actual text change with before/after text,
rule, confidence, and MinerU page/block index. Human-readable reports are also
written to `reports/preprocessing/<source>.md`.

The layered pipeline normalizes Unicode and controls, detects repeated page-edge
headers/footers, removes page numbers, repairs conservative PDF line-break
hyphenation, and detects OCR review candidates. It protects formulas and inline
values in prose; validated tables receive the relevant text cleanup before their
serialized content is protected. Pint adds SI annotations while preserving source
values and units. Unit interpretation uses local context: ambiguous prose
quantities remain unchanged, while explicit table headings can provide units for
numeric cells. Celsius quantities in prose are recorded without changing their
text; Celsius table values with explicit headers receive Kelvin annotations.
Context-sensitive aliases are normalized conservatively, and ambiguous symbols
are not guessed. Valid dates get an ISO annotation, configured
abbreviations expand at first use, and final checks preserve numeric tokens and
protected formulas/tables.

Camelot extracts validated tables using the configured parser settings. If its
result does not meet the configured thresholds, the pipeline falls back to the
MinerU table and records the reason. Unique MinerU `header` blocks remain,
including structured content omitted from Markdown.

`uv sync` installs required preprocessing dependencies, including Camelot,
`ftfy`, `regex`, `pandas`, and `pint`. SymPy formula validation is enabled
in `configs/preprocessing.yaml` and requires `uv sync --extra formulas`. All
original strings are retained even when parsing fails.

`configs/preprocessing.yaml` holds the repeated-furniture threshold, the
abbreviation dictionary, and reviewed OCR corrections. OCR corrections require
an exact source token and nearby literal context. The default correction list
is empty; suspects are reported without speculative replacements. Temperatures
in Celsius are recorded without rewriting the prose. Explicit table headings
provide context for Celsius-to-kelvin annotations. Source notation and values are
retained alongside normalized forms. Output text and reports are deterministic
for a fixed extraction and configuration.

## Configure paired GraphRAG workspaces

GraphRAG 3.2.0 is pinned in `pyproject.toml` and `uv.lock`. The shared
configuration template and prompts are in `configs/graphrag/`. The configured
local embedding service uses the `qwen3-embedding-4b` served model name and a
2560-dimensional vector store. Set the remote OpenAI-compatible generation
endpoint, model name and API key in the ignored repository-root `.env` (copy
`.env.example` first if needed). Keep both API keys out of `.env.example`.

    uv run python -m metallab graph setup
    uv run python -m metallab graph validate
    uv run python -m metallab graph validate --runtime

Setup creates `data/dirty/graphrag/` and `data/clean/graphrag/`. Each settings
file points at its arm's two prepared `.txt` files, so each arm builds one graph
from both PDFs. Model settings, prompts, entity types, extraction settings,
800-token chunks, 120-token overlap, and seed 42 are shared. Only storage
locations differ. GraphML and raw extracted graph snapshots are enabled.
Validation writes a credential-free `validation.json` in each workspace and
checks both settings through GraphRAG's own config loader. `--runtime` checks
that required environment variables are set, but does not call either service.
The following command runs the normal GraphRAG model-connectivity preflight
before it starts indexing:

    uv run python -m metallab index --arm dirty
    uv run python -m metallab index --arm clean

Indexing can incur remote API usage. Both saved workspaces have been indexed;
these commands rerun an arm. The indexing CLI rejects configuration drift
before launching GraphRAG. Use the
same remote generation service and local vLLM service for both arm runs.

## Other CLI commands

    uv run metallab config-show
    uv run metallab evaluate --arm dirty
    uv run metallab evaluate --arm clean
    uv run metallab compare

Evaluation reads saved GraphRAG Parquet outputs without calling model APIs.
It writes per-arm JSON and GraphML, then paired CSV and Markdown reports after
both arms have been evaluated. See [docs/metrics.md](docs/metrics.md) for the
documented topology and preservation metrics. Keep credentials only in the
ignored `.env` or exported environment variables.

## Checks

    uv run pytest
    uv run ruff check .
    uv run ruff format --check .
