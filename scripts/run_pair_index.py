"""Run the already validated dirty and clean GraphRAG indexes in order.

The paired workspace validator is the authority for settings parity. This script
records run metadata and refuses to continue if shared configuration changes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as parquet
from dotenv import load_dotenv

from metallab.graph import validate_workspaces

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
ARMS = ("dirty", "clean")


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_report(arm: str, report: dict) -> None:
    destination = REPORTS / f"run_{arm}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)


def output_count(arm: str, table: str) -> int | None:
    path = ROOT / "data" / arm / "graphrag" / "output" / f"{table}.parquet"
    return parquet.ParquetFile(path).metadata.num_rows if path.is_file() else None


def tracked_files() -> dict[str, str]:
    paths = [
        ROOT / "configs" / "experiment.yaml",
        ROOT / "configs" / "graphrag" / "entity_types.yaml",
        ROOT / "configs" / "graphrag" / "settings.template.yaml",
        ROOT / "configs" / "embeddings" / "vllm.yaml",
        *(ROOT / "configs" / "graphrag" / "prompts").glob("*.txt"),
        *(ROOT / "data" / arm / "graphrag" / "settings.yaml" for arm in ARMS),
    ]
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    REPORTS.mkdir(parents=True, exist_ok=True)
    workspaces = validate_workspaces(
        ROOT / "configs" / "experiment.yaml",
        ROOT / "configs" / "graphrag",
        ROOT / "configs" / "embeddings" / "vllm.yaml",
        runtime=True,
    )
    validations = {
        workspace.arm: json.loads((workspace.root / "validation.json").read_text(encoding="utf-8"))
        for workspace in workspaces
    }
    shared_hashes = {item["shared_settings_sha256"] for item in validations.values()}
    if len(shared_hashes) != 1:
        raise RuntimeError("Dirty and clean settings have different shared configuration hashes")
    frozen_files = tracked_files()
    base = {
        "graphrag_version": validations["dirty"]["graphrag_version"],
        "generation_model": validations["dirty"]["generation_model"],
        "embedding_model": validations["dirty"]["embedding_model"],
        "configuration_hash": next(iter(shared_hashes)),
        "chunking": validations["dirty"]["chunking"],
    }
    reports: dict[str, dict] = {}
    for workspace in workspaces:
        arm = workspace.arm
        report = {
            **base,
            "arm": arm,
            "status": "pending",
            "start_time": None,
            "end_time": None,
            "input_document_count": len(workspace.inputs),
            "input_documents": [path.name for path in workspace.inputs],
            "input_sha256": validations[arm]["input_sha256"],
            "chunk_count": None,
            "settings_sha256": validations[arm]["settings_sha256"],
            "prompt_sha256": validations[arm]["prompt_sha256"],
            "output_document_count": None,
            "entity_count": None,
            "relationship_count": None,
            "log_path": f"reports/index_{arm}.log",
        }
        reports[arm] = report
        write_report(arm, report)

    for workspace in workspaces:
        arm = workspace.arm
        report = reports[arm]
        if tracked_files() != frozen_files:
            report.update(status="failed", end_time=now(), error="Shared configuration changed")
            write_report(arm, report)
            print(f"{arm}: shared configuration changed; stopped", flush=True)
            return 2
        report.update(status="running", start_time=now())
        write_report(arm, report)
        print(f"{arm}: started {report['start_time']}", flush=True)
        log_path = REPORTS / f"index_{arm}.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "metallab", "index", "--arm", arm],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            last_update = time.monotonic()
            while process.poll() is None:
                time.sleep(5)
                if time.monotonic() - last_update >= 30:
                    print(
                        f"{arm}: indexing; current chunk count={output_count(arm, 'text_units')}",
                        flush=True,
                    )
                    last_update = time.monotonic()
        report.update(
            end_time=now(),
            chunk_count=output_count(arm, "text_units"),
            output_document_count=output_count(arm, "documents"),
            entity_count=output_count(arm, "entities"),
            relationship_count=output_count(arm, "relationships"),
            exit_code=process.returncode,
        )
        if tracked_files() != frozen_files:
            report.update(status="failed", error="Shared configuration changed during indexing")
        elif process.returncode != 0:
            report.update(status="failed", error=f"GraphRAG exited with code {process.returncode}")
        elif report["chunk_count"] is None or report["chunk_count"] == 0:
            report.update(status="failed", error="No GraphRAG text units were written")
        elif report["entity_count"] is None or report["relationship_count"] is None:
            report.update(status="failed", error="GraphRAG graph output tables are missing")
        else:
            report["status"] = "completed"
        write_report(arm, report)
        print(
            f"{arm}: {report['status']}; chunks={report['chunk_count']}; "
            f"entities={report['entity_count']}; relationships={report['relationship_count']}",
            flush=True,
        )
        if report["status"] != "completed":
            other = "clean" if arm == "dirty" else None
            if other and reports[other]["status"] == "pending":
                reports[other]["status"] = "not_started_due_to_dirty_failure"
                write_report(other, reports[other])
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
