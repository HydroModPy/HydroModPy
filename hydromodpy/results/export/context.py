"""Shared context object the FAIR views of a run or a job are rendered from.

A :class:`FairExportContext` is a pure-data view of one directory. It is
built once from the directory alone
(:func:`~hydromodpy.results.export.directory.context_from_directory`) and
handed to the RO-Crate, STAC and PROV-O builders. No view reads the index:
a run handed to somebody else renders the same views.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from hydromodpy.core.io.atomic_replace import rename_over_open_file
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    text = str(value)
    return text or None


def _is_missing(val: Any) -> bool:
    """Return True when the value is empty, None, NaN or pandas NA."""
    if val is None:
        return True
    if isinstance(val, str):
        return val == ""
    try:
        return bool(pd.isna(val))
    except (TypeError, ValueError):
        # A list or an array has no single missing value.
        return False


def _coalesce(row: dict[str, Any], key: str) -> Any:
    if row is None:
        return None
    val = row.get(key)
    if _is_missing(val):
        return None
    return val


@dataclass(frozen=True)
class AssetEntry:
    """One referenced artifact (Zarr, Parquet, COG, lockfile)."""

    key: str
    relative_path: str
    media_type: str
    roles: tuple[str, ...]
    sha256: str | None = None
    size_bytes: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class InputEntry:
    """One workspace input file used by the simulation."""

    role: str
    category: str
    original_path: str
    sha256: str
    size_bytes: int
    source_type: str | None = None
    source_ref: str | None = None
    loader_name: str | None = None
    license: str | None = None
    data_provider: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class FairExportContext:
    """Read-only snapshot of every piece of metadata the exporters need."""

    sim_id: str
    sim_row: dict[str, Any]
    runs_env: dict[str, Any]
    workspace_meta: dict[str, Any]
    workspace_path: Path
    license_url: str
    creator_name: str | None
    creator_email: str | None
    assets: tuple[AssetEntry, ...]
    inputs: tuple[InputEntry, ...]
    lockfile_path: Path | None
    solver_binary_sha256: str | None
    solver_name: str | None
    solver_version: str | None
    hydromodpy_version: str
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        row = self.sim_row
        if not row:
            return None
        keys = ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax")
        if any(_is_missing(row.get(k)) for k in keys):
            return None
        return tuple(float(row[k]) for k in keys)  # type: ignore[return-value]

    @property
    def period_start(self) -> str | None:
        return _iso(_coalesce(self.sim_row, "period_start"))

    @property
    def period_end(self) -> str | None:
        return _iso(_coalesce(self.sim_row, "period_end"))


def to_json(payload: Any, path: Path) -> Path:
    """Write *payload* as sorted UTF-8 JSON, whole, through a temporary file and one rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{uuid4().hex}")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rename_over_open_file(tmp, path)
    return path


__all__ = [
    "AssetEntry",
    "FairExportContext",
    "InputEntry",
    "to_json",
]
