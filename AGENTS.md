# AGENTS.md

## Project goal

Build a reproducible experiment comparing two knowledge graphs constructed
from the same two PDF documents:

- data/source/stat3.pdf
- data/source/tanaka1981.pdf

The experiment has two pipelines:

1. DIRTY:
   PDF -> MinerU -> minimally modified extracted text -> GraphRAG

2. CLEAN:
   PDF -> MinerU -> preprocessing -> normalized structured text -> GraphRAG

Both PDFs must contribute to ONE graph in each pipeline.

The goal is to measure how preprocessing affects:
- graph structure and connectivity
- preservation of formulas, tables, numbers and units
- answers to short, source-checked metallurgical questions

## Important experimental rule

Dirty and clean experiments MUST use identical:

- source PDFs
- MinerU version
- GraphRAG version
- generation LLM
- generation prompts
- embedding model
- entity types
- chunk size
- chunk overlap
- extraction settings

The only intentional difference should be preprocessing.

Do not silently change GraphRAG configuration between dirty and clean.

## Architecture

Use:

- MinerU for PDF parsing
- Microsoft GraphRAG for graph construction
- vLLM as a local OpenAI-compatible embeddings server
- a multilingual embedding model
- remote OpenAI-compatible API for text generation
- NetworkX for graph algorithms and metrics
- pandas for Parquet analysis

Recommended embedding model:

Qwen/Qwen3-Embedding-4B

Local API:

http://127.0.0.1:8000/v1

## Expected repository structure

data/
  source/
  mineru/
  dirty/
  clean/

src/
  extraction/
  preprocessing/
  graph/
  evaluation/

configs/
  graphrag/
  embeddings/

scripts/

reports/

tests/

## Preprocessing requirements

Clean preprocessing should preserve semantic information.

Implement:

- Unicode normalization
- control-character removal
- whitespace normalization
- repeated page header/footer detection
- PDF hyphenation repair
- OCR artifact detection/correction
- abbreviation normalization
- numeric value preservation
- unit normalization
- date normalization
- table preservation
- formula preservation

Never globally lowercase technical text.

Never globally remove stop words.

Never blindly replace OCR characters like 0/O or 1/l.

Never destroy the original representation of formulas or values.

If a value is normalized, preserve both forms, e.g.:

15 MPa [SI: 15000000 Pa]

## Protected structures

Before aggressive text cleanup protect:

- formulas
- tables
- numbers with units
- abbreviations

Possible temporary markers:

[MATH_0001]
[TABLE_0001]
[NUMUNIT_0001]

Restore the structures after cleanup.

## Graph evaluation

Load:

- entities.parquet
- relationships.parquet

Convert them to NetworkX graphs.

Calculate:

- node count
- edge count
- density
- connected components
- largest connected component
- isolated nodes
- degree distribution
- average degree
- median degree
- max degree
- bridges
- articulation points
- cycle basis
- cyclomatic number
- clustering coefficient
- average shortest path in largest connected component

Also calculate:

- degree centrality
- betweenness centrality
- PageRank

## Evaluation metrics

Evaluate graph topology and formula/table preservation from the saved
GraphRAG and MinerU artifacts. Keep the source structures available for
inspection and report what can be checked without invented labels.

## Cross-document analysis

Because two PDFs form one graph, calculate:

- entities appearing in both documents
- document-specific entities
- cross-document edges
- cross-document edge ratio

## Reproducibility

Save:

- Python version
- package versions
- MinerU version
- GraphRAG version
- vLLM version
- embedding model name
- generation model name
- prompts
- GraphRAG settings
- random seeds

Use seed 42 where supported.

## Coding rules

- Python 3.12
- use pathlib instead of raw path strings where practical
- use type annotations
- use logging instead of print for pipeline code
- configuration must not be hardcoded when it belongs in YAML/.env
- never commit API keys
- provide CLI scripts for major pipeline stages
- code should be runnable stage-by-stage
- do not implement the whole project in one monolithic script
- add tests for preprocessing functions
- preserve raw intermediate artifacts for debugging

## Working style

Implement the project incrementally.

Before making major architectural changes:
1. inspect existing repository
2. explain intended modification briefly
3. implement
4. run relevant tests
5. report what changed and what remains

Do not rewrite working components unnecessarily.

## Operating environment

Target OS:

Ubuntu Linux

Do not create Windows-specific scripts unless explicitly requested.

Use `uv` for:

- Python installation/version management where appropriate
- virtual environments
- dependency installation
- dependency locking
- running project commands

Do NOT use:

- `python -m venv`
- bare `pip install`
- Poetry
- Conda

Typical environment setup:

```bash
uv python install 3.12
uv venv --python 3.12 .venv
source .venv/bin/activate
uv sync