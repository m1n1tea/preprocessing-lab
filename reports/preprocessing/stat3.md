# CLEAN preprocessing: stat3

- Input: `/home/mmakruov/experements/graphrag-preprocessing-lab/data/mineru/stat3/structured_content.json`
- Output: `/home/mmakruov/experements/graphrag-preprocessing-lab/data/clean/input/stat3.txt`
- Pages: 10
- Characters: 21573 → 22146
- Integrity: passed

## Transformations

- `abbreviation_expansion`: 2
- `abbreviation_protected`: 68
- `abbreviation_restored`: 68
- `ambiguous_quantities`: 0
- `control_codepoints_removed`: 0
- `formula_protected`: 1
- `formula_restored`: 1
- `formula_validation_failures`: 1
- `hyphenation_repair`: 97
- `integrity_validated`: 1
- `invalid_mineru_tables`: 0
- `number_unit_protected`: 27
- `number_unit_restored`: 27
- `number_units_detected`: 69
- `number_units_recognized`: 69
- `ocr_suspects`: 1
- `page_number_removed`: 10
- `pint_normalized_quantities`: 69
- `table_protected`: 1
- `table_restored`: 1
- `tables_from_camelot`: 1
- `tables_from_mineru`: 0
- `unit_header_normalization`: 7
- `unit_normalization`: 69
- `unresolved_ocr_warnings`: 1
- `whitespace_normalization`: 5

## Tables

- stat3-T001 page 8: Camelot, valid=True, 7×13, issues=none

## Formula checks

- stat3-F001 page 9: SymPy=False; SymPy could not parse the complete formula: LaTeXParsingError

## OCR and processing warnings

- OCR: page 10, replacement_character: � — Unicode replacement character
