"""Run the same reviewed questions against both GraphRAG workspaces and search modes."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "reports/factual_query_questions.csv"
OUTPUT = ROOT / "reports/factual_query_answers"
QUERY_ROOT = ROOT / "reports/query_settings"
ARMS = ("dirty", "clean")
DEFAULT_METHODS = ("local", "global")
RESPONSE_TYPE = (
    "One sentence of at most 25 words. Give only the requested fact, number, or equation "
    "with a source citation. If the source does not contain it, say Not found."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_questions(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(
        None in row or not row.get("query_id") or not row.get("query_text") for row in rows
    ):
        raise ValueError(
            "The question file needs valid query_id and query_text fields in every row"
        )
    return rows


async def _run_one(
    row: dict[str, str], arm: str, method: str, semaphore: asyncio.Semaphore, timeout: int
) -> dict[str, Any]:
    query_id = row["query_id"]
    query = row["query_text"]
    path = OUTPUT / f"{query_id}_{arm}_{method}.json"
    if path.is_file():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if prior.get("exit_code") == 0 and prior.get("query") == query:
            print(f"SKIP {query_id} {arm} {method}: saved successful result", flush=True)
            return prior

    async with semaphore:
        command = [
            sys.executable,
            "-m",
            "graphrag",
            "query",
            "--root",
            str(QUERY_ROOT / arm),
            "--method",
            method,
            "--response-type",
            RESPONSE_TYPE,
            query,
        ]
        environment = os.environ.copy()
        environment.update({"NO_COLOR": "1", "TERM": "dumb"})
        started_at = datetime.now(UTC).isoformat()
        start = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=ROOT,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            exit_code = process.returncode
            error = None
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            exit_code = None
            error = f"Timed out after {timeout} seconds"
        result = {
            "query_id": query_id,
            "arm": arm,
            "method": method,
            "query": query,
            "started_at": started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.monotonic() - start, 2),
            "exit_code": exit_code,
            "error": error,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
        _write_json(path, result)
        print(
            f"DONE {query_id} {arm} {method}: exit={exit_code} "
            f"seconds={result['duration_seconds']} path={path.relative_to(ROOT)}",
            flush=True,
        )
        return result


async def _main(concurrency: int, timeout: int, methods: tuple[str, ...]) -> int:
    load_dotenv(ROOT / ".env", override=False)
    rows = _read_questions(QUERIES)
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        _run_one(row, arm, method, semaphore, timeout)
        for method in methods
        for row in rows
        for arm in ARMS
    ]
    results = await asyncio.gather(*tasks)
    successes = sum(result["exit_code"] == 0 for result in results)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "graphrag_version": version("graphrag"),
        "generation_model": os.getenv("GENERATION_MODEL"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "qwen3-embedding-4b"),
        "query_file": str(QUERIES.relative_to(ROOT)),
        "query_file_sha256": _sha256(QUERIES),
        "settings_sha256": {arm: _sha256(QUERY_ROOT / arm / "settings.yaml") for arm in ARMS},
        "response_type": RESPONSE_TYPE,
        "search_methods": list(methods),
        "query_count": len(rows),
        "run_count": len(results),
        "success_count": successes,
        "failure_count": len(results) - successes,
        "runs": [
            {
                key: result[key]
                for key in (
                    "query_id",
                    "arm",
                    "method",
                    "duration_seconds",
                    "exit_code",
                    "error",
                )
            }
            for result in results
        ],
    }
    _write_json(OUTPUT / "manifest.json", manifest)
    print(f"SUMMARY {successes}/{len(results)} successful", flush=True)
    return 0 if successes == len(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=("local", "global", "drift", "basic"),
        default=DEFAULT_METHODS,
        help="Search methods to run (default: local global)",
    )
    arguments = parser.parse_args()
    if arguments.concurrency < 1 or arguments.timeout < 1:
        parser.error("concurrency and timeout must be positive")
    raise SystemExit(
        asyncio.run(_main(arguments.concurrency, arguments.timeout, tuple(arguments.methods)))
    )
