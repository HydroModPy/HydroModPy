"""Shared contract helpers for site-selection manifest files."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SITE_SELECTION_MANIFEST_NAME = "site_selection_manifest.json"
MANIFEST_SCHEMA_VERSION = "site_selection_manifest_v1"
REQUIRED_MANIFEST_KEYS = (
    "schema_version",
    "created_at_utc",
    "selection_id",
    "action",
    "output_root",
    "strategy",
    "territory",
    "input",
    "criteria",
    "counts",
    "outputs",
)
REQUIRED_OUTPUT_KEYS = (
    "criteria_components_jsonl",
    "site_selection_decisions_jsonl",
    "site_selection_manifest_json",
)


def write_selection_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    """Write a site-selection manifest as stable JSON."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def load_selection_manifest(path: str | Path) -> dict[str, Any]:
    """Load a site-selection manifest."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def manifest_output_path(
    manifest: Mapping[str, Any],
    key: str,
    *,
    manifest_path: str | Path | None = None,
) -> Path | None:
    """Resolve one output path from a manifest, or return ``None`` when absent."""

    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        return None
    value = outputs.get(key)
    if not value:
        return None
    output_root = manifest_output_root(manifest, manifest_path=manifest_path)
    return resolve_manifest_output_path(str(value), output_root=output_root)


def manifest_output_root(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str | Path | None,
) -> Path:
    """Resolve the manifest output root, falling back to the manifest directory."""

    raw_root = manifest.get("output_root")
    if raw_root:
        root = Path(str(raw_root)).expanduser()
        if root.is_absolute():
            return root.resolve()
    if manifest_path is not None:
        base = Path(manifest_path).expanduser().resolve().parent
        if raw_root:
            return (base / str(raw_root)).resolve()
        return base
    if raw_root:
        return Path(str(raw_root)).expanduser().resolve()
    return Path.cwd().resolve()


def resolve_manifest_output_path(value: str, *, output_root: Path) -> Path:
    """Resolve a manifest output entry against its output root."""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (output_root / path).resolve()


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "REQUIRED_MANIFEST_KEYS",
    "REQUIRED_OUTPUT_KEYS",
    "SITE_SELECTION_MANIFEST_NAME",
    "load_selection_manifest",
    "manifest_output_path",
    "manifest_output_root",
    "resolve_manifest_output_path",
    "write_selection_manifest",
]
