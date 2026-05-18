"""Workspace ``data/`` layout helpers.

Variables under ``<workspace>/data/`` are split into two subdirectories:

- ``raw/``: immutable inputs as fetched upstream. Each file has a JSON sidecar.
- ``processed/``: derivatives reconstructible from ``raw/`` (clipped rasters,
  re-projected vectors, resampled time series, etc.).

This separation follows the Cookiecutter Data Science pattern and matches the
Snakemake immutable/derived split. Spec: ``reports_db/99_master.md §5`` and
``reports_db/22_migration_plan.md §3``.
"""

from __future__ import annotations

from pathlib import Path

DATA_DIRNAME = "data"
RAW_DIRNAME = "raw"
PROCESSED_DIRNAME = "processed"


def variable_dir(workspace: Path, variable: str) -> Path:
    """Return ``<workspace>/data/<variable>/``."""
    return Path(workspace).expanduser().resolve() / DATA_DIRNAME / variable


def raw_dir(workspace: Path, variable: str) -> Path:
    """Return ``<workspace>/data/<variable>/raw/``."""
    return variable_dir(workspace, variable) / RAW_DIRNAME


def processed_dir(workspace: Path, variable: str) -> Path:
    """Return ``<workspace>/data/<variable>/processed/``."""
    return variable_dir(workspace, variable) / PROCESSED_DIRNAME


def ensure_data_layout(workspace: Path, variable: str) -> tuple[Path, Path]:
    """Create the ``raw/`` and ``processed/`` directories for one variable.

    Returns
    -------
    tuple[Path, Path]
        ``(raw_dir, processed_dir)``.
    """
    raw = raw_dir(workspace, variable)
    processed = processed_dir(workspace, variable)
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    return raw, processed


__all__ = [
    "DATA_DIRNAME",
    "PROCESSED_DIRNAME",
    "RAW_DIRNAME",
    "ensure_data_layout",
    "processed_dir",
    "raw_dir",
    "variable_dir",
]
