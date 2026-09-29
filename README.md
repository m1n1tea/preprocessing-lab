# Metallurgical GraphRAG preprocessing experiment

This repository compares one knowledge graph built from the raw MinerU extraction
of two metallurgical PDFs with one graph built from cleaned extraction of those
same PDFs. Both documents will contribute to one graph in each arm. MinerU,
GraphRAG, models, prompts, and extraction settings must be shared between arms.

PDF extraction, both corpus preparation stages, paired GraphRAG workspace setup and
validation, the standard-index command, and graph evaluation are implemented. The
DIRTY arm currently has an indexed graph; the CLEAN arm has not been indexed yet.

## Setup on Ubuntu

Install uv if needed, then run:

    uv python install 3.12
    uv sync --locked
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
the two files are ingested together in one dirty GraphRAG workspace.

The current Tanaka Markdown omits final-page references 138-146 because MinerU
classified them as headers; the dirty stage intentionally preserves that output
as-is. Their text remains in MinerU's structured JSON for later analysis.

## Build the clean corpus

    uv run python -m metallab prepare --arm clean

This validates both MinerU outputs and reads each `structured_content.json` rather
than the Markdown. It writes `data/clean/input/stat3.txt` and
`data/clean/input/tanaka1981.txt` for a future shared clean GraphRAG workspace.
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
`ftfy`, `regex`, `pandas`, and `pint`. Optional SymPy formula validation is
available with `uv sync --extra formulas` and remains disabled by default.

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

Indexing can incur remote API usage and has not been run by setup or validation.
The indexing CLI rejects configuration drift before launching GraphRAG. Use the
same remote generation service and local vLLM service for both arm runs.

## Other CLI commands

    uv run metallab config-show
    uv run metallab evaluate --arm dirty
    uv run metallab evaluate --arm clean
    uv run metallab compare

Evaluation reads saved GraphRAG Parquet outputs and reviewed files under
`data/gold/`; it does not call model APIs. It writes per-arm JSON and GraphML,
then paired CSV and Markdown reports after both arms have been evaluated. See
[docs/metrics.md](docs/metrics.md) for metric definitions and gold CSV schemas.
Gold-dependent scores remain null until reviewed annotations exist. Keep
credentials only in the ignored `.env` or exported environment variables.

## Checks

    uv run pytest
    uv run ruff check .
    uv run ruff format --check .
