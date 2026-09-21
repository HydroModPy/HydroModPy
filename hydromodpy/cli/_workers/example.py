"""Private worker helpers for ``hmp example`` actions.

The verbs themselves live in :mod:`hydromodpy._api`; what is here is the
flattening into the plain rows the command modules print, plus the dev-only
manifest generator, which has no Python surface of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy._api import example_add, example_list, example_show
from hydromodpy.examples.blobs import is_cached, missing_bytes
from hydromodpy.examples.install import InstallReport
from hydromodpy.examples.manifest import ExampleEntry, ExampleFile


def list_rows() -> list[dict[str, Any]]:
    """Describe every catalogued example, with what this machine still misses."""
    return [_summary(entry) for entry in example_list()]


def show_rows(example_id: str) -> dict[str, Any]:
    """Describe one example file by file, each marked cached or missing."""
    entry = example_show(example_id)
    summary = _summary(entry)
    summary["files"] = [_file_row(item, "project") for item in entry.files]
    summary["data"] = [_file_row(item, "data") for item in entry.data]
    return summary


def add_to_workspace(
    example_id: str,
    *,
    workspace: Any,
    ref: str | None = None,
    force: bool = False,
) -> InstallReport:
    """Fetch what is missing, verify it, and write the example into the workspace."""
    return example_add(example_id, workspace=workspace, ref=ref, force=force)


def generate_manifest(
    *,
    root: Path | None = None,
    destination: Path | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    """Rewrite ``catalog.toml`` from a checkout and describe what it now holds."""
    from hydromodpy.examples.generate import write_catalog

    written, entries = write_catalog(root, destination)
    return written, [_summary(entry) for entry in entries]


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


def _summary(entry: ExampleEntry) -> dict[str, Any]:
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


def _file_row(item: ExampleFile, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "dest": item.dest,
        "repo_path": item.repo_path,
        "size": item.size,
        "sha256": item.sha256,
        "cached": is_cached(item),
    }
