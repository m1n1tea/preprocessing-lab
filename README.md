# Metallurgical GraphRAG preprocessing experiment

This repository compares one knowledge graph built from the raw MinerU extraction
of two metallurgical PDFs with one graph built from cleaned extraction of those
same PDFs. Both documents will contribute to one graph in each arm. MinerU,
GraphRAG, models, prompts, and extraction settings must be shared between arms.

PDF extraction and both corpus preparation stages are implemented. GraphRAG indexing
and evaluation are not implemented yet.

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
two files will later be ingested together in one dirty GraphRAG workspace.

The current Tanaka Markdown omits final-page references 138-146 because MinerU
classified them as headers; the dirty stage intentionally preserves that output
as-is. Their text remains in MinerU's structured JSON for later analysis.

## Build the clean corpus

    uv run python -m metallab prepare --arm clean

This validates both MinerU outputs and reads each `structured_content.json` rather
than the Markdown. It writes `data/clean/input/stat3.txt` and
`data/clean/input/tanaka1981.txt` for a future shared clean GraphRAG workspace.
Every run also writes `data/clean/reports/<source>.json` with stage counts, OCR
suspects, page/block references for protected formulas and tables, and final
integrity status. `data/clean/audit/<source>.jsonl` records each actual text
change with its original and resulting text and MinerU page/block index.

The pipeline protects formula and table blocks before cleaning prose and restores
them exactly. It normalizes Unicode and whitespace, removes recurring
headers/footers and page numbers, repairs conservative line-break hyphenation,
identifies OCR suspects, annotates unambiguous SI unit conversions and full
calendar dates, and expands configured abbreviations at first use. It checks
that original numeric tokens and protected technical structures remain. Unique
MinerU `header` blocks are retained; this includes Tanaka references 138–146
that MinerU omitted from its Markdown.

`configs/preprocessing.yaml` holds the repeated-furniture threshold, the
abbreviation dictionary, and reviewed OCR corrections. OCR corrections require
an exact source token and nearby literal context. The default correction list
is empty; suspects are reported without speculative replacements. Temperatures
in Celsius are recognized but not converted to Kelvin without knowing whether
they represent absolute values or differences. Output text and reports are
deterministic for a fixed extraction and configuration.

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
    uv run metallab compare

Evaluation commands remain reserved and exit clearly as unimplemented. Keep
credentials only in the ignored `.env` or exported environment variables.

## Checks

    uv run pytest
    uv run ruff check .
    uv run ruff format --check .
