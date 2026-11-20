"""The plain rows that ``hmp example list`` and ``hmp example show`` print.

Each function reads the shipped catalog and flattens an entry into dicts, so
the command modules only format them.
"""

from __future__ import annotations

from typing import Any

from hydromodpy.core.payload.index import PayloadFile
from hydromodpy.project.examples.blobs import is_cached, missing_bytes
from hydromodpy.project.examples.manifest import ExampleEntry, find_entry, load_catalog


def show_rows(example_id: str) -> dict[str, Any]:
    """Describe one example file by file, each marked cached or missing."""
    entry = find_entry(example_id, load_catalog())
    row = summary(entry)
    row["files"] = [_file_row(item, "project") for item in entry.files]
    row["data"] = [_file_row(item, "data") for item in entry.data]
    return row


def human_size(size: int) -> str:
    """Render a byte count the way a download is read, never below one decimal."""
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB"):
        value /= 1024.0
        if value < 1024.0 or unit == "GiB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GiB"


def summary(entry: ExampleEntry) -> dict[str, Any]:
    """Describe one catalog entry, with what this machine still misses of it."""
    return {
        "id": entry.id,
        "directory": entry.directory,
        "title": entry.title,
        "summary": entry.summary,
        "runtime": entry.runtime,
        "entry_config": entry.entry_config,
        "file_count": len(entry.payload),
        "total_size": entry.total_size,
        "missing_size": missing_bytes(entry.payload),
    }


def _file_row(item: PayloadFile, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "dest": item.dest,
        "repo_path": item.repo_path,
        "size": item.size,
        "sha256": item.sha256,
        "cached": is_cached(item),
    }
