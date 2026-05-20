from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb


TABLE_NAME = "execution_knowledge_records"


@dataclass(slots=True)
class IngestionResult:
    rows_read: int
    rows_ingested: int
    rows_skipped: int


def _safe_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _normalize_record(payload: dict[str, Any]) -> dict[str, Any]:
    execution = payload.get("execution") or {}
    system = payload.get("system") or {}
    hardware = payload.get("hardware") or {}
    runtime = payload.get("runtime") or {}
    solver = payload.get("solver") or {}
    logs = payload.get("logs") or {}
    exception = payload.get("exception")
    artifacts = payload.get("artifacts") or {}
    provenance = payload.get("provenance") or {}
    validation = payload.get("validation") or {}

    gpu_block = hardware.get("gpu")
    if isinstance(gpu_block, list) and gpu_block:
        first_gpu = gpu_block[0] if isinstance(gpu_block[0], dict) else {}
    elif isinstance(gpu_block, dict):
        first_gpu = gpu_block
    else:
        first_gpu = {}

    run_id = _as_text(payload.get("run_id"))
    schema_version = _as_text(payload.get("schema_version")) or "v1"
    status = _as_text(payload.get("status")) or "unknown"
    started_at = _as_text(payload.get("started_at"))
    ended_at = _as_text(payload.get("ended_at"))
    workspace = _as_text(payload.get("workspace"))

    if not run_id or not started_at or not workspace:
        raise ValueError("Missing required fields: run_id, started_at, or workspace")

    return {
        "run_id": run_id,
        "schema_version": schema_version,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "workspace": workspace,
        "solver_name": _as_text(execution.get("solver"))
        or _as_text(solver.get("solver_name")),
        "solver_iterations": _as_int(
            execution.get("iteration") if execution.get("iteration") is not None else solver.get("iterations")
        ),
        "solver_converged": _as_bool(solver.get("converged")),
        "solver_status": _as_text(solver.get("solver_status")),
        "cpu_count": _as_int(hardware.get("cpu_count")),
        "cpu_usage_percent": _as_float(hardware.get("cpu_usage_percent")),
        "ram_total_mb": _as_float(hardware.get("ram_total_mb")),
        "ram_used_mb": _as_float(hardware.get("ram_used_mb")),
        "ram_percent": _as_float(hardware.get("ram_percent")),
        "gpu_name": _as_text(first_gpu.get("name")) or _as_text(hardware.get("gpu_name")),
        "gpu_memory_total_mb": _as_float(
            first_gpu.get("memory_total_mb") if first_gpu.get("memory_total_mb") is not None else hardware.get("gpu_memory_total_mb")
        ),
        "gpu_memory_used_mb": _as_float(
            first_gpu.get("memory_used_mb") if first_gpu.get("memory_used_mb") is not None else hardware.get("gpu_memory_used_mb")
        ),
        "gpu_utilization_percent": _as_float(
            first_gpu.get("utilization_percent")
            if first_gpu.get("utilization_percent") is not None
            else hardware.get("gpu_utilization_percent")
        ),
        "os_name": _as_text(system.get("os_name")),
        "os_release": _as_text(system.get("os_release")),
        "os_version": _as_text(system.get("os_version")),
        "machine": _as_text(system.get("machine")),
        "python_version": _as_text(system.get("python_version")),
        "pid": _as_int(runtime.get("pid")),
        "ppid": _as_int(runtime.get("ppid")),
        "process_name": _as_text(runtime.get("process_name")),
        "command_line": _safe_json(runtime.get("command_line") or []),
        "working_directory": _as_text(runtime.get("working_directory")),
        "environment": _safe_json(runtime.get("environment") or {}),
        "uptime_seconds": _as_float(runtime.get("uptime_seconds")),
        "elapsed_seconds": _as_float(runtime.get("elapsed_seconds")),
        "logs": _safe_json(logs),
        "exception": _safe_json(exception),
        "execution": _safe_json(execution),
        "results": _safe_json(payload.get("results") or {}),
        "artifacts": _safe_json(artifacts),
        "provenance": _safe_json(provenance),
        "validation": _safe_json(validation),
        "raw_payload": _safe_json(payload),
    }


def ensure_table(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            run_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ,
            workspace TEXT NOT NULL,

            solver_name TEXT,
            solver_iterations INTEGER,
            solver_converged BOOLEAN,
            solver_status TEXT,

            cpu_count INTEGER,
            cpu_usage_percent DOUBLE,
            ram_total_mb DOUBLE,
            ram_used_mb DOUBLE,
            ram_percent DOUBLE,

            gpu_name TEXT,
            gpu_memory_total_mb DOUBLE,
            gpu_memory_used_mb DOUBLE,
            gpu_utilization_percent DOUBLE,

            os_name TEXT,
            os_release TEXT,
            os_version TEXT,
            machine TEXT,
            python_version TEXT,

            pid INTEGER,
            ppid INTEGER,
            process_name TEXT,
            command_line JSON,
            working_directory TEXT,
            environment JSON,
            uptime_seconds DOUBLE,
            elapsed_seconds DOUBLE,

            logs JSON,
            exception JSON,
            execution JSON,
            results JSON,
            artifacts JSON,
            provenance JSON,
            validation JSON,
            raw_payload JSON
        )
        """
    )


def ingest_jsonl_file(
    jsonl_path: str | Path,
    duckdb_path: str | Path,
    *,
    table_name: str = TABLE_NAME,
    on_conflict: str = "replace",
) -> IngestionResult:
    jsonl_path = Path(jsonl_path).expanduser().resolve()
    duckdb_path = Path(duckdb_path).expanduser().resolve()

    connection = duckdb.connect(str(duckdb_path))
    ensure_table(connection)

    rows_read = 0
    rows_ingested = 0
    rows_skipped = 0

    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue

            rows_read += 1

            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("JSONL record must be an object")
                record = _normalize_record(payload)
            except Exception:
                rows_skipped += 1
                continue

            columns = list(record.keys())
            placeholders = ", ".join(["?"] * len(columns))
            column_sql = ", ".join(columns)
            values = [record[column] for column in columns]

            if on_conflict == "replace":
                connection.execute(
                    f"""
                    INSERT INTO {table_name} ({column_sql})
                    VALUES ({placeholders})
                    ON CONFLICT(run_id) DO UPDATE SET
                        schema_version = excluded.schema_version,
                        status = excluded.status,
                        started_at = excluded.started_at,
                        ended_at = excluded.ended_at,
                        workspace = excluded.workspace,
                        solver_name = excluded.solver_name,
                        solver_iterations = excluded.solver_iterations,
                        solver_converged = excluded.solver_converged,
                        solver_status = excluded.solver_status,
                        cpu_count = excluded.cpu_count,
                        cpu_usage_percent = excluded.cpu_usage_percent,
                        ram_total_mb = excluded.ram_total_mb,
                        ram_used_mb = excluded.ram_used_mb,
                        ram_percent = excluded.ram_percent,
                        gpu_name = excluded.gpu_name,
                        gpu_memory_total_mb = excluded.gpu_memory_total_mb,
                        gpu_memory_used_mb = excluded.gpu_memory_used_mb,
                        gpu_utilization_percent = excluded.gpu_utilization_percent,
                        os_name = excluded.os_name,
                        os_release = excluded.os_release,
                        os_version = excluded.os_version,
                        machine = excluded.machine,
                        python_version = excluded.python_version,
                        pid = excluded.pid,
                        ppid = excluded.ppid,
                        process_name = excluded.process_name,
                        command_line = excluded.command_line,
                        working_directory = excluded.working_directory,
                        environment = excluded.environment,
                        uptime_seconds = excluded.uptime_seconds,
                        elapsed_seconds = excluded.elapsed_seconds,
                        logs = excluded.logs,
                        exception = excluded.exception,
                        execution = excluded.execution,
                        results = excluded.results,
                        artifacts = excluded.artifacts,
                        provenance = excluded.provenance,
                        validation = excluded.validation,
                        raw_payload = excluded.raw_payload
                    """,
                    values,
                )
            else:
                connection.execute(
                    f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
                    values,
                )

            rows_ingested += 1

    connection.close()
    return IngestionResult(
        rows_read=rows_read,
        rows_ingested=rows_ingested,
        rows_skipped=rows_skipped,
    )


def ingest_jsonl_directory(
    directory: str | Path,
    duckdb_path: str | Path,
    *,
    pattern: str = "*.jsonl",
    on_conflict: str = "replace",
) -> list[IngestionResult]:
    directory = Path(directory).expanduser().resolve()
    results: list[IngestionResult] = []

    for jsonl_path in sorted(directory.glob(pattern)):
        if jsonl_path.is_file():
            results.append(
                ingest_jsonl_file(
                    jsonl_path,
                    duckdb_path,
                    on_conflict=on_conflict,
                )
            )

    return results