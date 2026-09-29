# Clean text preprocessing pipeline

This document describes the current implementation that produces the text files in `data/clean/input/`. It describes code behavior; the repository currently contains no generated clean corpus to inspect.

## Entry point and inputs

Run the stage from the repository root:

```bash
uv run python -m metallab prepare --arm clean
```

The CLI's `prepare` command calls `build_clean_corpus()` in `src/metallab/preprocessing/runner.py`. The default configuration files are `configs/experiment.yaml`, `configs/mineru.yaml`, and `configs/preprocessing.yaml`; the CLI also accepts `--config`, `--mineru-config`, and `--preprocessing-config` overrides.

The stage first calls `validate_extraction()` for both PDFs. This checks the saved MinerU artifacts against the source PDFs and shared MinerU settings. It then reads `data/mineru/<source-id>/structured_content.json` for each source listed in the experiment configuration: `stat3` and `tanaka1981`. The clean stage uses structured pages and typed blocks, not MinerU's `markdown.md`. Pages and blocks are processed in their JSON order. Each PDF becomes its own `.txt` file; the two files are intended to be ingested together into one clean GraphRAG workspace.

`configs/preprocessing.yaml` supplies the minimum number of distinct pages needed to recognize repeated page furniture, a dictionary of abbreviations, and reviewed OCR correction rules. The current policy sets the furniture threshold to `2`, expands `КП` and `УО`, and has **no** OCR correction rules. The runner validates the policy's required fields before processing either document.

## Processing one document

1. **Find repeated page furniture.** Across the document, `repeated_furniture()` considers only blocks whose type is `header` or `footer`. For matching, it removes whitespace and applies case folding to their content, then counts distinct page indices. A header or footer with the same normalized text on at least the configured number of pages is dropped wherever it occurs. A unique header or footer is retained, even if MinerU classified body content as a header. Every `page_number` block is dropped independently. These removals are recorded in the audit.

2. **Protect whole table and equation blocks.** A `table` block is serialized as `Table`, an optional caption, a newline, and its original MinerU HTML content. An `equation` block is serialized as `Formula`, an optional caption, and its original content between `$$` delimiters. The serialized block is temporarily replaced with an opaque marker. The table or formula body therefore bypasses prose cleanup and is restored unchanged at the end. Captions come from nonempty `captions[].content` values. If an `image` or `chart` block has no content but does have captions, it becomes `Figure: <captions>`; there is no image OCR or image file insertion at this stage. Empty nontechnical blocks are skipped.

3. **Protect inline technical spans in other blocks.** `protect_inline_values()` temporarily replaces recognized number-with-unit spans and configured abbreviation tokens with markers. It keeps their exact original spelling and spacing through the first cleanup stages. Overlapping matches are resolved by start position and then longer span. These markers are restored *before* OCR correction and unit or abbreviation annotation. Protection is local to each prose block; table and equation protection uses a separate document-level registry.

4. **Clean prose.** The pipeline applies Unicode NFC normalization, removes control characters except line breaks and tabs, then normalizes line endings, horizontal whitespace, spaces around line breaks, and runs of three or more line breaks. It trims the block. Next it joins a conservative subset of PDF-split words: a hyphen followed by a line break or spaces is removed only when both fragments are alphabetic Cyrillic, each has at least two letters, and the right fragment is lowercase. Latin compounds and other hyphenation patterns remain as extracted. Inline markers are then restored.

5. **Inspect and optionally correct OCR.** A detector records mixed letter/digit tokens matching its pattern as OCR suspects; detection alone does not change text. Corrections use only configured `source`, `target`, and literal `context` rules. A rule replaces a whole-token source only when its context appears within 120 characters before or after the match in the same block. The default rule list is empty, so current runs only report suspects. There is no general `0`/`O` or `1`/`l` substitution.

6. **Annotate numbers, dates, and abbreviations.** The number-with-unit recognizer counts matches. `normalize_units()` appends SI values for supported unambiguous units while preserving the original expression, including numeric ranges where recognized: for example, `15 MPa [SI: 15000000 Pa]`. Supported conversions include pressure units (`MPa`, `GPa`, `N/mm²` and Cyrillic variants), lengths (`mm`, `cm`, `µm` and Cyrillic variants), and minutes/seconds. The recognizer also sees Celsius, Kelvin, percentages, and weight percentages, but the current conversion table does not convert those. `normalize_dates()` adds an ISO annotation to valid `DD.MM.YYYY` dates, such as `31.12.1981 [ISO: 1981-12-31]`; invalid dates stay unchanged. `expand_abbreviations()` appends the configured full form at the first whole-token occurrence of each abbreviation per document, leaving later occurrences as written. The original short form remains in the annotation.

7. **Validate and assemble.** After each nonempty prose block, `validate_numeric_values()` requires every numeric token in that block's source text to still occur at least as often in its result. Retained block outputs are joined with a blank line and a final newline. Document-level table and formula markers are restored. `validate_integrity()` rejects empty output, leftover protected markers, or missing protected table/formula content. A final document-level numeric-token check compares all retained raw blocks with the assembled text. These checks protect original digit sequences and protected block contents; they do not prove that every word, mathematical meaning, or table relationship is correct.

No stage globally lowercases technical text or removes stop words. The pipeline does not paraphrase prose or normalize the interior of formulas and tables.

## Output files and audit trail

For each source ID, the stage writes:

| Path | Contents |
| --- | --- |
| `data/clean/input/<source-id>.txt` | Final UTF-8 text for GraphRAG. The configured source IDs produce `stat3.txt` and `tanaka1981.txt`. |
| `data/clean/reports/<source-id>.json` | Source ID, page and block counts, output length, per-stage counts, OCR suspects, locations and kinds of protected table/formula blocks, and `integrity: "passed"`. |
| `data/clean/audit/<source-id>.jsonl` | One JSON record per actual text change, with stage, before/after text, zero-based MinerU `page` index, and zero-based `block` index. |

The report's OCR suspect entries and protected-structure locations use one-based `page` numbers; audit change records retain zero-based page indices. Stage counts have different meanings: cleanup counts changed blocks, replacement stages count individual substitutions, and recognition/protection counts count matches. They are not all counts of changed characters or blocks.

Both documents are fully processed in memory before any output is published. Each individual output file is then written through a temporary file and atomically replaced. Thus a processing failure in the second document leaves no newly published files from this run, but publication of the complete set of six files is not one atomic transaction. A rerun with unchanged extraction and policy writes deterministic content.

## Scope and practical limits

The clean output has no explicit page or block IDs in its text: those locations are available in the audit and report. Unique MinerU headers remain, which preserves potentially misclassified content such as the Tanaka references discussed in `README.md`. A genuinely repeated header or footer is removed based on its block type and text, so this classification and threshold merit inspection when reviewing the corpus.

The OCR suspect regex can also flag legitimate technical tokens such as `Fe3C`; a suspect is a review cue, not a diagnosed error. Only configured exact corrections change OCR text. Unit and date annotations cover the implemented patterns and conversion table, not all possible scientific notations. Numeric validation checks token presence and counts, not semantic equivalence. Table HTML and formula text are preserved from MinerU, so extraction errors already present there remain in the clean corpus.

The dirty corpus stage reads MinerU `markdown.md` byte-for-byte, while this clean stage reads `structured_content.json`. That distinction matters when interpreting dirty/clean differences: structured MinerU output may contain blocks omitted from its Markdown, independently of the prose cleanup rules. See `src/metallab/corpus/dirty.py` and `README.md` for the dirty path.

## Code map

- `src/metallab/cli.py`: `prepare --arm clean` dispatch and CLI error handling.
- `src/metallab/preprocessing/runner.py`: policy validation, document/block orchestration, integrity checks, reports, and file publication.
- `src/metallab/preprocessing/stages.py`: text transformations, protection registry, audit records, and validation helpers.
- `configs/experiment.yaml`: source IDs and output paths.
- `configs/preprocessing.yaml`: clean-specific policy.
- `tests/test_clean_corpus.py` and `tests/test_preprocessing_stages.py`: end-to-end fixture and transformation behavior checks.
