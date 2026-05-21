"""Script d'ingestion simple JSONL -> DuckDB.

Usage:
  python scripts/ingest_runner.py --jsonl /path/to/runtime_capture.jsonl --duckdb /path/to/catalog.duckdb
  python scripts/ingest_runner.py --dir /path/to/execution_knowledge --duckdb /path/to/catalog.duckdb
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.validity_frame.storage.ingest_jsonl_to_duckdb import ingest_jsonl_directory, ingest_jsonl_file


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--jsonl", type=str, help="Path to a single .jsonl file to ingest")
    group.add_argument("--dir", type=str, help="Directory containing .jsonl files to ingest")
    parser.add_argument("--duckdb", type=str, required=True, help="Path to target duckdb file (will be created if missing)")
    parser.add_argument("--pattern", type=str, default="*.jsonl", help="Glob pattern when using --dir")
    args = parser.parse_args()

    duckdb_path = Path(args.duckdb).expanduser().resolve()

    try:
        if args.jsonl:
            jsonl_path = Path(args.jsonl).expanduser().resolve()
            if not jsonl_path.exists():
                print("jsonl file not found:", jsonl_path, file=sys.stderr)
                sys.exit(2)
            result = ingest_jsonl_file(jsonl_path, duckdb_path)
            print(f"Ingested {result.rows_ingested}/{result.rows_read} rows, skipped {result.rows_skipped}")
        else:
            directory = Path(args.dir).expanduser().resolve()
            if not directory.exists():
                print("directory not found:", directory, file=sys.stderr)
                sys.exit(2)
            results = ingest_jsonl_directory(directory, duckdb_path, pattern=args.pattern)
            total_read = sum(result.rows_read for result in results)
            total_ingested = sum(result.rows_ingested for result in results)
            total_skipped = sum(result.rows_skipped for result in results)
            print(f"Ingested {total_ingested}/{total_read} rows across {len(results)} files, skipped {total_skipped}")
    except Exception as exc:
        print("Ingestion failed:", exc, file=sys.stderr)
        raise


if __name__ == "__main__":
    main()