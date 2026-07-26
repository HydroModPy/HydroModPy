"""Result-storage layout contract: what one run and one session directory hold.

A project keeps one index database, one directory per run and one directory
per calibration session::

    <project>/.hmp/index.duckdb          index, rebuildable from the disk
    <project>/runs/<name>/               one run, named after the run itself
        fields.zarr/                     array store (always a directory)
        tables.parquet/<view>.parquet    tabular payloads
        config.toml                      frozen resolved configuration
        provenance.json                  environment, versions, git
        manifest.json                    seal, written last
        annotations.json                 tags and notes, mutable after the seal
        trash.json                       present while the run sits in the trash
        figures/                         figures of this run
    <project>/sessions/<name>/           one calibration session
        session.json                     identity, search space, best trial
        trials.jsonl                     one line per evaluated trial

The run directory name is the human run name (with its ``.vN`` version
suffix), so the tree is readable without the index. The directory names of
the project itself (``runs``, ``sessions``, ``share``, ``.hmp`` ...) live in
:mod:`hydromodpy.core.state.paths`; this module owns the names *inside* a
run or session directory so path builders, exporters and documentation share
one vocabulary.

A run directory holds results, not diagnostics: the pipeline log stays in
``<project>/.hmp/logs/``, which is disposable, while everything listed above
is sealed by ``manifest.json`` with its size. A log still open when the seal
is written could not carry an honest size, so it is not a run artefact.

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

RUN_MANIFEST_FILENAME = "manifest.json"
"""Seal of a complete run directory. Absent means the run did not finish."""

RUN_ANNOTATIONS_FILENAME = "annotations.json"
"""Tags and notes of one run. Written after the seal, like the trash marker."""

RUN_TRASH_FILENAME = "trash.json"
"""Trash marker of one run. Present means trashed; absent means live."""

RUN_FIGURES_DIRNAME = "figures"
"""Figures rendered for one run."""

SESSION_DESCRIPTOR_FILENAME = "session.json"
"""Identity, search space, objective and best trial of one calibration session."""

SESSION_TRIALS_FILENAME = "trials.jsonl"
"""Trial journal of one session, appended one JSON object per line as it runs."""


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
    "RUN_MANIFEST_FILENAME",
    "RUN_PROVENANCE_FILENAME",
    "RUN_STORAGE_LAYER_NAMES",
    "RUN_TRASH_FILENAME",
    "SESSION_DESCRIPTOR_FILENAME",
    "SESSION_TRIALS_FILENAME",
    "ResultStorageLayer",
    "StorageScope",
    "TABLES_DIRNAME",
]
