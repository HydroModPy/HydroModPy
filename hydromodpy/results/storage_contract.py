"""Shared result-storage layout contract.

HydroModPy keeps one workspace-level catalog database and per-simulation
artefacts below the workspace ``simulations`` directory. This module centralises
that vocabulary so path builders, documentation-oriented tests, and public
facades do not drift back toward ambiguous "one database per run" language.

The catalog filename itself lives in
:mod:`hydromodpy.core.state.paths` so every layer (core, results, cli, data)
shares one canonical definition.

Parquet naming
--------------
Two distinct shapes coexist on disk and both happen to end in ``.parquet``:

* **Container directory** (``PARQUET_DIR_SUFFIX``): the per-simulation folder
  ``<basename>.parquet/`` that groups every view payload for one run.
* **Single-file payload** (``PARQUET_FILE_SUFFIX``): the individual
  ``<view>.parquet`` files placed inside the container directory.

Because both literals are the same string, naive ``glob("*.parquet")`` calls
are ambiguous. Callers that walk the workspace must therefore filter by
``Path.is_dir()`` or ``Path.is_file()`` to disambiguate intent.

``PARQUET_DATASET_MARKER`` is reserved for the future Hive-partitioned dataset
layout (``<view>.parquet/<part=...>/...``). It is not used by the current v1
contract; new partitioned datasets must place this subdirectory marker at
their root so directory-walking code can detect them without a heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hydromodpy.core.state.paths import CATALOG_FILENAME

StorageScope = Literal["workspace", "simulation"]

SIMULATIONS_DIRNAME = "simulations"

ZARR_SUFFIX = ".zarr"
ZARR_ZIP_SUFFIX = ".zarr.zip"
PARQUET_DIR_SUFFIX = ".parquet"
PARQUET_FILE_SUFFIX = ".parquet"
PARQUET_DATASET_MARKER = "_dataset"


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
    "PARQUET_DATASET_MARKER",
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
