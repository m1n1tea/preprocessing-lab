from pathlib import Path
from runpy import run_path

import pytest

_read_questions = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/run_graphrag_queries.py")
)["_read_questions"]


def test_query_csv_rejects_unquoted_comma(tmp_path: Path) -> None:
    path = tmp_path / "questions.csv"
    path.write_text(
        "query_id,query_text,source_document\n"
        "f10,What is Eq. (8), the Hall-Petch relation?,tanaka1981.pdf\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="valid query_id"):
        _read_questions(path)


def test_query_csv_accepts_quoted_comma(tmp_path: Path) -> None:
    path = tmp_path / "questions.csv"
    path.write_text(
        "query_id,query_text,source_document\n"
        'f10,"What is Eq. (8), the Hall-Petch relation?",tanaka1981.pdf\n',
        encoding="utf-8",
    )
    assert _read_questions(path)[0]["query_text"] == "What is Eq. (8), the Hall-Petch relation?"
