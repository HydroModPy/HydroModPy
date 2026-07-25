"""Result-storage layout contract: what one run directory holds.

A project keeps one index database and one directory per run::

    <project>/.hmp/index.duckdb          index, rebuildable from the runs
    <project>/runs/<name>/               one run, named after the run itself
        fields.zarr/                     array store (always a directory)
        tables.parquet/<view>.parquet    tabular payloads
        config.toml                      frozen resolved configuration
        provenance.json                  environment, versions, git
        figures/                         figures of this run
        run.log                          run journal

The run directory name is the human run name (with its ``.vN`` version
suffix), so the tree is readable without the index. The directory names of
the project itself (``runs``, ``share``, ``.hmp`` ...) live in
:mod:`hydromodpy.core.state.paths`; this module owns the names *inside* a
run directory so path builders, exporters and documentation share one
vocabulary.

There is no packed form: ``fields.zarr`` is a directory that readers open
directly while the run is still solving, and the tabular payloads are plain
``.parquet`` files. No suffix ever marks a container.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hydromodpy.core.state.paths import CATALOG_FILENAME, INTERNAL_DIRNAME, RUNS_DIRNAME

StorageScope = Literal["project", "run"]

FIELDS_STORE_NAME = "fields.zarr"
"""Zarr directory store of one run."""

TABLES_DIRNAME = "tables.parquet"
"""Directory grouping the Parquet payloads of one run."""

PARQUET_FILE_SUFFIX = ".parquet"
"""Suffix of a single Parquet payload inside :data:`TABLES_DIRNAME`."""

RUN_CONFIG_FILENAME = "config.toml"
"""Frozen resolved configuration of one run."""

RUN_PROVENANCE_FILENAME = "provenance.json"
"""Environment, versions and git state of one run."""

RUN_FIGURES_DIRNAME = "figures"
"""Figures rendered for one run."""

RUN_LOG_FILENAME = "run.log"
"""Journal of one run."""


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
        "project",
        f"<project>/{INTERNAL_DIRNAME}/{CATALOG_FILENAME}",
        "Project-level DuckDB index for runs, metadata, metrics, and provenance.",
    ),
    ResultStorageLayer(
        "zarr",
        "run",
        f"<project>/{RUNS_DIRNAME}/<run>/{FIELDS_STORE_NAME}",
        "Per-run array store for meshes, spatial fields, forcings, and rasters.",
    ),
    ResultStorageLayer(
        "parquet",
        "run",
        f"<project>/{RUNS_DIRNAME}/<run>/{TABLES_DIRNAME}/<view>{PARQUET_FILE_SUFFIX}",
        "Per-run tabular payloads exposed through DuckDB views.",
    ),
)

PROJECT_STORAGE_LAYER_NAMES: tuple[str, ...] = tuple(
    layer.name for layer in RESULT_STORAGE_LAYERS if layer.scope == "project"
)
RUN_STORAGE_LAYER_NAMES: tuple[str, ...] = tuple(
    layer.name for layer in RESULT_STORAGE_LAYERS if layer.scope == "run"
)


__all__ = [
    "FIELDS_STORE_NAME",
    "PARQUET_FILE_SUFFIX",
    "PROJECT_STORAGE_LAYER_NAMES",
    "RESULT_STORAGE_LAYERS",
    "RUN_CONFIG_FILENAME",
    "RUN_FIGURES_DIRNAME",
    "RUN_LOG_FILENAME",
    "RUN_PROVENANCE_FILENAME",
    "RUN_STORAGE_LAYER_NAMES",
    "ResultStorageLayer",
    "StorageScope",
    "TABLES_DIRNAME",
]
