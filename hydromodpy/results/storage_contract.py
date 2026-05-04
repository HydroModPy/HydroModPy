"""Shared result-storage layout contract.

HydroModPy keeps one workspace-level catalog database and per-simulation
artefacts below the workspace ``simulations`` directory. This module centralises
that vocabulary so path builders, documentation-oriented tests, and public
facades do not drift back toward ambiguous "one database per run" language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StorageScope = Literal["workspace", "simulation"]

CATALOG_FILENAME = "hydromodpy.duckdb"
SIMULATIONS_DIRNAME = "simulations"

ZARR_SUFFIX = ".zarr"
ZARR_ZIP_SUFFIX = ".zarr.zip"
PARQUET_DIR_SUFFIX = ".parquet"
PARQUET_FILE_SUFFIX = ".parquet"


@dataclass(frozen=True, slots=True)
class ResultStorageLayer:
    """One physical storage layer used by persisted simulation results."""

    name: str
    scope: StorageScope
    path_template: str
    role: str


RESULT_STORAGE_LAYERS: tuple[ResultStorageLayer, ...] = (
    ResultStorageLayer(
        "catalog",
        "workspace",
        f"<workspace>/{CATALOG_FILENAME}",
        "Workspace-level DuckDB index for simulations, metadata, metrics, and provenance.",
    ),
    ResultStorageLayer(
        "zarr",
        "simulation",
        f"<workspace>/{SIMULATIONS_DIRNAME}/<basename>{ZARR_SUFFIX}",
        "Per-simulation array store for meshes, spatial fields, forcings, and rasters.",
    ),
    ResultStorageLayer(
        "parquet",
        "simulation",
        (
            f"<workspace>/{SIMULATIONS_DIRNAME}/"
            f"<basename>{PARQUET_DIR_SUFFIX}/<view>{PARQUET_FILE_SUFFIX}"
        ),
        "Per-simulation tabular payloads exposed through DuckDB views.",
    ),
)

WORKSPACE_STORAGE_LAYER_NAMES: tuple[str, ...] = tuple(
    layer.name for layer in RESULT_STORAGE_LAYERS if layer.scope == "workspace"
)
SIMULATION_STORAGE_LAYER_NAMES: tuple[str, ...] = tuple(
    layer.name for layer in RESULT_STORAGE_LAYERS if layer.scope == "simulation"
)


__all__ = [
    "CATALOG_FILENAME",
    "PARQUET_DIR_SUFFIX",
    "PARQUET_FILE_SUFFIX",
    "RESULT_STORAGE_LAYERS",
    "ResultStorageLayer",
    "SIMULATION_STORAGE_LAYER_NAMES",
    "SIMULATIONS_DIRNAME",
    "StorageScope",
    "WORKSPACE_STORAGE_LAYER_NAMES",
    "ZARR_SUFFIX",
    "ZARR_ZIP_SUFFIX",
]
