# CLEAN preprocessing pipeline

The CLEAN arm reads MinerU `structured_content.json` for `stat3` and `tanaka1981`, preserving document identities and producing separate UTF-8 files for the shared future GraphRAG workspace.

Run it from the repository root:

```bash
uv run python -m metallab prepare --arm clean
```

The default paths are configured in `configs/experiment.yaml`, `configs/mineru.yaml`, and `configs/preprocessing.yaml`. Policy validation and extraction validation run before processing. Both documents are processed in memory before artifacts are published.

## Stages

The pipeline applies independent, logged stages in this order:

1. Route validated tables through the CLEAN text stages before protecting their serialized content. Protect equation blocks and inline abbreviation and number/unit spans in prose.
2. Apply Unicode NFC normalization and guarded `ftfy` repair. A repair is accepted only when technical token checks remain stable; otherwise the original text is retained and a warning is recorded.
3. Remove control characters and normalize line endings, whitespace, and blank lines.
4. Detect repeated text in the configured page-edge lines across pages. Remove only recurring headers/footers, plus explicit MinerU page-number blocks and standalone page-number lines. Unique header blocks remain.
5. Repair conservative PDF line-break hyphenation. Known terms and configured prefixes guide English cases; Cyrillic splits are joined only when the right fragment is lowercase. Chemical symbols and ordinary within-line hyphens are retained.
6. Detect OCR review candidates. The detector reports mixed letter/digit tokens and suspicious glyph patterns without guessing corrections. Only reviewed rules with exact token and literal context can change text; the configured correction list is empty.
7. Add Pint SI annotations to supported quantities while keeping their original representation and numeric value. Celsius quantities in prose are recorded without rewriting their text. Numeric table cells with explicit Celsius column headings receive Kelvin annotations. Valid `DD.MM.YYYY` dates receive an ISO annotation. Configured abbreviations expand at first use while retaining the short form.
8. Restore protected values, the selected table extraction, and formulas; validate markers, output non-emptiness, and numeric-token preservation against the selected text/table representation.

No global lowercasing, stop-word removal, or aggressive lemmatization is performed. Unit conversions and other non-trivial edits are recorded in the audit. Values that cannot be safely parsed stay unchanged.

## Tables and formulas

Camelot lattice is the primary table extractor for CLEAN. MinerU identifies candidate table pages; Camelot rereads those source PDF pages and extracts cells from the printed layout. The runner records parser quality measures, validates table shape and numeric preservation, and serializes cells without pandas numeric inference. Clear line-wrap artifacts inside numeric ranges are repaired conservatively. If Camelot returns no acceptable table, the report records the rejection and the pipeline uses MinerU's table; invalid fallback content remains preserved.

Validated tables run through the relevant CLEAN text stages used for prose: NFC, control and whitespace cleanup, conservative dehyphenation, OCR suspect detection and approved corrections, quantity recognition, date normalization, and abbreviation expansion. Header units provide context for numeric cells, and Pint conversions are appended while source values and notation are retained. Context-sensitive unit aliases are normalized only when the nearby measurement and table structure support that reading; ambiguous symbols are not guessed. Table edits and quantity records are written to the audit. Invalid raw fallback content remains preserved.

Formula text is protected and restored exactly. Optional SymPy LaTeX validation is available with the `formulas` extra and is disabled by default; reports state when validation was not run. Camelot is a required dependency for CLEAN table extraction.

## Outputs and audit

| Path | Purpose |
| --- | --- |
| `data/clean/input/<document>.txt` | Final GraphRAG input, one file per PDF |
| `data/clean/reports/<document>.json` | Machine-readable counts, validation, OCR candidates, quantities, tables, formulas, and paths |
| `data/clean/audit/<document>.jsonl` | One record per text transformation, with document, stage, rule, confidence, page, block, and before/after text |
| `reports/preprocessing/<document>.json` | Run report copy |
| `reports/preprocessing/<document>.md` | Human-readable summary |

JSON reports use one-based page numbers for review. Audit records identify MinerU blocks with one-based page numbers. Counts are stage-specific: some count text edits, others recognized quantities or protected structures. Reports retain raw OCR candidates for human review; a candidate is not a confirmed OCR error.

## Corpus notes

Both source documents retain separate identities through extraction and CLEAN
preparation. Structured MinerU content can contain blocks that are absent from
its Markdown output; unique content is retained when eligible. OCR candidates
are reported for review, while automatic corrections require configured,
context-specific rules.

Tests live in `tests/test_preprocessing_stages.py` and `tests/test_clean_corpus.py`. Run `uv run pytest` and `uv run ruff check .` to verify the project.

## Relationship to evaluation metrics

The preprocessing report's `integrity: "passed"` is a stage validation flag,
not a 0–1 formula or table score. The evaluator computes Formula Integrity and
Table Integrity by comparing source structures—or the selected CLEAN table
output—with each arm's final input corpus. See [metrics.md](metrics.md) for these definitions and the
other graph, gold-label, traversal, and retrieval metrics.
