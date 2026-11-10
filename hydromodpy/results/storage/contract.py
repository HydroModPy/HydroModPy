"""Result-storage layout contract: what one run and one session directory hold.

A project keeps one index database, one directory per run and one directory
per calibration session. Every artifact is written in the directory of what
produced it, under a name fixed by its class::

    <project>/.hmp/index.duckdb          index, rebuildable from the disk
    <project>/runs/<name>/               one run, named after the run itself
        outcome.json                     issue of the attempt, written first and last
        request.json                     the run request as given in JSON or as a dict, never redacted
        config.toml                      frozen configuration: what the run was given
        config.resolved.toml             the same with every default, and what the build decided
        inputs.json                      every loaded input: provider, product, sha256, licence
        provenance.json                  environment, versions, git, binaries
        manifest.json                    seal, written last
        fields.zarr/                     array store (always a directory)
        final_state/                     last heads, lake and reach stages in float64, Zarr 3
        tables.parquet/<view>.parquet    tabular payloads; simulation.parquet is the index row
        annotations.json                 tags and notes, mutable after the seal
        profile.json                     time and memory of each step, solve, figure, export
        ro-crate-metadata.json ...       generated views, on request, after the seal
        README.md                        generated from the seal, sha256 of the manifest in its footer
        figures/  + index.json           figures of this run and their ledger
        exports/  + index.json           deliverables of this run and their ledger
        report/index.html                rendered report
        logs/                            run log, heartbeat.json
        published.jsonl                  where this run was published, one line per copy
        attempts/<n>/                    outcome.json, logs/ and stop.json of an earlier attempt
        .hmp/                            scratch, locks, checkpoints, stop flag of the running attempt
    <project>/sessions/<name>/           one calibration session
        outcome.json                     issue of the session
        config.toml                      frozen resolved configuration of the case
        session.json                     identity, search space, best trial, status
        trials.jsonl                     one line per evaluated trial, trial unique per case
        methods.md                       the method, in words
        phases/<phase>/session.json      descriptor of one phase: status, frozen, best
        trials/<n>/                      kept trials, each in the form of a run
        trial_series/trial-NNNNNN.parquet  opt-in: simulated/observed series of one trial
        candidates/                      TOML overlays of materialized candidates
        README.md  figures/  report/  logs/

The run directory name is the human run name (with its ``.vN`` version
suffix), so the tree is readable without the index. The directory names of
the project itself (``runs``, ``sessions``, ``plan``, ``trash``, ``.hmp`` ...)
live in :mod:`hydromodpy.core.state.layout`; this module owns the names
*inside* a run or session directory so path builders, exporters and
documentation share one vocabulary.

The seal inventories the raw result only: what :data:`UNSEALED_RUN_ENTRIES`
names is derived, mutable, diagnostic or machine state, and ``manifest.json``
never lists it. A log still open when the seal is written could not carry an
honest size; a figure is rendered again on request; the outcome changes after
the seal.

There is no packed form: ``fields.zarr`` is a directory that readers open
directly while the run is still solving, and the tabular payloads are plain
``.parquet`` files. No suffix ever marks a container.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hydromodpy.core.state.layout import (
    CATALOG_FILENAME,
    INTERNAL_DIRNAME,
    RUNS_DIRNAME,
    TRIALS_DIRNAME,
)
from hydromodpy.schema.generated_views import GENERATED_VIEWS

StorageScope = Literal["project", "run"]

FIELDS_STORE_NAME = "fields.zarr"
"""Zarr directory store of one run."""

TABLES_DIRNAME = "tables.parquet"
"""Directory grouping the Parquet payloads of one run."""

PARQUET_FILE_SUFFIX = ".parquet"
"""Suffix of a single Parquet payload inside :data:`TABLES_DIRNAME`."""

RUN_CONFIG_FILENAME = "config.toml"
"""Frozen configuration of one run: what it was given. A replay reads this file."""

RUN_RESOLVED_CONFIG_FILENAME = "config.resolved.toml"
"""Whole configuration of one run, defaults written. A replay compares against it."""

RUN_PROVENANCE_FILENAME = "provenance.json"
"""Environment, versions and git state of one run."""

RUN_SEARCH_TABLE = "searched_under"
"""Table of ``config.resolved.toml``: the ``[calibration]`` section a promoted run came from."""

RUN_MANIFEST_FILENAME = "manifest.json"
"""Seal of a complete run directory. Absent means the run did not finish."""

RUN_PRODUCTS_FILENAME = "products.json"
"""The products the run read from the store, one per kind, in first-demand order."""

FINAL_STATE_DIRNAME = "final_state"
"""Zarr 3 group of the last state of a run, in float64 and compressed without loss.

It holds ``head`` (``nlay``, ``ncpl``, NaN on inactive cells), ``lake_stage``
with the attribute ``lake_ids``, ``sfr_stage`` with the attribute ``reaches``
when SFR routes with storage, and the attribute ``at``, the end of the last
period. A restart and the next window of a chain read it, so it is sealed
with the run and kept at every retention level.
"""

RUN_PROFILE_FILENAME = "profile.json"
"""Time and memory of each step, solve, figure and export of one run, ``hydromodpy.profile.v1``.

It is rewritten after each step and keeps the lines of every attempt. It says
how the run went on one machine, not what it computed, so it is outside the
seal and outside the identity.
"""

RUN_ANNOTATIONS_FILENAME = "annotations.json"
"""Tags and notes of one run. The one file written after the seal."""

RUN_FIGURES_DIRNAME = "figures"
"""Figures rendered for one run."""

RUN_OUTCOME_FILENAME = "outcome.json"
"""Issue of the current attempt: status, attempt, host, pid, exit code, error."""

RUN_REQUEST_FILENAME = "request.json"
"""The request of a run given as JSON or as a dict, written at the claim, never redacted.

It is outside the seal: it says how the run was asked for, and ``config.toml``
says what the run was given.
"""

RUN_INPUTS_FILENAME = "inputs.json"
"""Every input the run loaded: provider, product, request, sha256, licence."""

README_FILENAME = "README.md"
"""Generated reading guide of a run, a session or a summary."""

RUN_PUBLISHED_FILENAME = "published.jsonl"
"""Where a run was published, one JSON line per copy. Absent until the first one."""

RUN_EXPORTS_DIRNAME = "exports"
"""Deliverables of one run, written by ``[[export]]`` requests."""

RUN_REPORT_DIRNAME = "report"
"""Rendered report of one run or session."""

RUN_LOGS_DIRNAME = "logs"
"""Run log and heartbeat of one run or session."""

RUN_LOG_FILENAME = "run.log"
"""Log of the current attempt, under :data:`RUN_LOGS_DIRNAME`; its tail goes to the outcome."""

RUN_ATTEMPTS_DIRNAME = "attempts"
"""Outcome and logs of the earlier attempts of one run, one directory per attempt."""

RUN_SOLVER_DIRNAME = "solver"
"""Raw solver folders of one run, kept only under ``keep_solver_files``.

Moved out of the attempt scratch before the seal, so they outlive
``<run>/.hmp/``. Not a result: the seal never inventories them.
"""

LEDGER_FILENAME = "index.json"
"""Ledger of a ``figures/`` or ``exports/`` directory: one entry per file."""

HEARTBEAT_FILENAME = "heartbeat.json"
"""Pulse of a running attempt, under :data:`RUN_LOGS_DIRNAME`."""

REPORT_INDEX_FILENAME = "index.html"
"""Entry page of a rendered report."""

SIMULATION_TABLE_NAME = "simulation"
"""Stem of the one-row index payload of a run inside :data:`TABLES_DIRNAME`."""

REQUIRED_RUN_ENTRIES: frozenset[str] = frozenset({FIELDS_STORE_NAME, TABLES_DIRNAME})
"""What a solved run always leaves behind."""

UNSEALED_RUN_ENTRIES: frozenset[str] = frozenset(
    {
        RUN_OUTCOME_FILENAME,
        RUN_REQUEST_FILENAME,
        RUN_ANNOTATIONS_FILENAME,
        README_FILENAME,
        RUN_PUBLISHED_FILENAME,
        RUN_FIGURES_DIRNAME,
        RUN_EXPORTS_DIRNAME,
        RUN_REPORT_DIRNAME,
        RUN_LOGS_DIRNAME,
        RUN_ATTEMPTS_DIRNAME,
        RUN_SOLVER_DIRNAME,
        RUN_PROFILE_FILENAME,
    }
    | GENERATED_VIEWS
)
"""Entries of a run directory the seal never inventories.

Derived (figures, exports, report, README, generated views), mutable after
the seal (outcome, annotations, published lines), diagnostic (logs, kept
solver folders, profile), history (attempts) or the request as it came (request). The runtime scratch of :data:`RUN_SCRATCH_ENTRIES`
is left out for a different reason: it is not a result.
"""

ALLOWED_RUN_ENTRIES: frozenset[str] = (
    REQUIRED_RUN_ENTRIES
    | frozenset(
        {
            RUN_CONFIG_FILENAME,
            RUN_RESOLVED_CONFIG_FILENAME,
            RUN_PROVENANCE_FILENAME,
            RUN_MANIFEST_FILENAME,
            RUN_INPUTS_FILENAME,
            RUN_PRODUCTS_FILENAME,
            FINAL_STATE_DIRNAME,
        }
    )
    | UNSEALED_RUN_ENTRIES
)
"""Every name a run directory may carry as an artifact.

Anything else found in a run directory is either the runtime scratch named by
:data:`RUN_SCRATCH_ENTRIES` or something the run did not declare.
"""

RUN_SCRATCH_ENTRIES: frozenset[str] = frozenset({INTERNAL_DIRNAME})
"""Runtime scratch a live run holds, which is not a result.

A run takes its locks under ``<run>/.hmp/locks/`` and reads its stop flag at
``<run>/.hmp/stop.json``. It is machine state with the
lifetime of the process, like the pipeline log, so the seal does not inventory
it: a manifest that lists a lock directory as an artifact of the run describes
the machine that ran it, not the run.
"""

SESSION_DESCRIPTOR_FILENAME = "session.json"
"""Identity, search space, objective, best trial and status of one session or phase."""

SESSION_TRIALS_FILENAME = "trials.jsonl"
"""Trial journal of one session, appended one JSON object per line as it runs."""

SESSION_TRIAL_SERIES_DIRNAME = "trial_series"
"""Opt-in per-trial simulated/observed series, one Parquet file per trial.

Written only when ``[calibration].persist_trial_series`` is on. Absent
otherwise: a session folder with no such directory simply did not opt in."""

SESSION_CONFIG_FILENAME = "config.toml"
"""Frozen resolved configuration of the calibrated case, the base of a promotion."""

SESSION_PHASES_DIRNAME = "phases"
"""One descriptor directory per phase of a staged calibration."""

SESSION_CANDIDATES_DIRNAME = "candidates"
"""TOML overlays of the candidates a session materialized."""

SESSION_METHODS_FILENAME = "methods.md"
"""The calibration method, in words, for the reader of the session."""

ALLOWED_SESSION_ENTRIES: frozenset[str] = frozenset(
    {
        RUN_OUTCOME_FILENAME,
        SESSION_CONFIG_FILENAME,
        SESSION_DESCRIPTOR_FILENAME,
        SESSION_TRIALS_FILENAME,
        SESSION_TRIAL_SERIES_DIRNAME,
        SESSION_METHODS_FILENAME,
        SESSION_PHASES_DIRNAME,
        TRIALS_DIRNAME,
        SESSION_CANDIDATES_DIRNAME,
        README_FILENAME,
        RUN_PUBLISHED_FILENAME,
        RUN_FIGURES_DIRNAME,
        RUN_REPORT_DIRNAME,
        RUN_LOGS_DIRNAME,
    }
)
"""Every name a session directory may carry. ``.hmp`` is its runtime scratch."""

PUBLICATION_FILENAME = "PUBLICATION.json"
"""Record of one published copy, written in the copy itself."""

PLAN_FILENAME = "plan.json"
"""Fingerprints, version, date, case count and budget of one immutable plan."""

PLAN_SITES_FILENAME = "sites.parquet"
"""Resolved site table of one plan."""

PLAN_CASES_FILENAME = "cases.parquet"
"""Cases of one plan: case_id, site, recipe, config_hash, config_path. No status."""


def session_trial_series_filename(trial: int) -> str:
    """Return the file name of one trial's series table, sortable by trial number."""
    return f"trial-{int(trial):06d}.parquet"


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


GEOGRAPHIC_FEATURE_PREFIX = "geographic_"
"""Prefix of the per-feature GeoParquet payloads inside ``tables.parquet``."""


def geographic_feature_files(tables_dir: Path) -> dict[str, Path]:
    """Return the GeoParquet payload of each vector layer a run stored, by layer name."""
    if not tables_dir.is_dir():
        return {}
    prefix, suffix = GEOGRAPHIC_FEATURE_PREFIX, PARQUET_FILE_SUFFIX
    return {
        path.name[len(prefix) : -len(suffix)]: path
        for path in sorted(tables_dir.glob(f"{prefix}*{suffix}"))
    }


__all__ = [
    "ALLOWED_RUN_ENTRIES",
    "ALLOWED_SESSION_ENTRIES",
    "REQUIRED_RUN_ENTRIES",
    "RUN_SCRATCH_ENTRIES",
    "UNSEALED_RUN_ENTRIES",
    "FIELDS_STORE_NAME",
    "FINAL_STATE_DIRNAME",
    "GEOGRAPHIC_FEATURE_PREFIX",
    "HEARTBEAT_FILENAME",
    "LEDGER_FILENAME",
    "PARQUET_FILE_SUFFIX",
    "PLAN_CASES_FILENAME",
    "PLAN_FILENAME",
    "PLAN_SITES_FILENAME",
    "PROJECT_STORAGE_LAYER_NAMES",
    "PUBLICATION_FILENAME",
    "README_FILENAME",
    "REPORT_INDEX_FILENAME",
    "RESULT_STORAGE_LAYERS",
    "RUN_ANNOTATIONS_FILENAME",
    "RUN_ATTEMPTS_DIRNAME",
    "RUN_CONFIG_FILENAME",
    "RUN_EXPORTS_DIRNAME",
    "RUN_FIGURES_DIRNAME",
    "RUN_INPUTS_FILENAME",
    "RUN_LOGS_DIRNAME",
    "RUN_LOG_FILENAME",
    "RUN_MANIFEST_FILENAME",
    "RUN_OUTCOME_FILENAME",
    "RUN_PRODUCTS_FILENAME",
    "RUN_PROFILE_FILENAME",
    "RUN_PROVENANCE_FILENAME",
    "RUN_PUBLISHED_FILENAME",
    "RUN_REPORT_DIRNAME",
    "RUN_REQUEST_FILENAME",
    "RUN_RESOLVED_CONFIG_FILENAME",
    "RUN_SEARCH_TABLE",
    "RUN_SOLVER_DIRNAME",
    "RUN_STORAGE_LAYER_NAMES",
    "SESSION_CANDIDATES_DIRNAME",
    "SESSION_CONFIG_FILENAME",
    "SESSION_DESCRIPTOR_FILENAME",
    "SESSION_METHODS_FILENAME",
    "SESSION_PHASES_DIRNAME",
    "SESSION_TRIALS_FILENAME",
    "SESSION_TRIAL_SERIES_DIRNAME",
    "SIMULATION_TABLE_NAME",
    "session_trial_series_filename",
    "ResultStorageLayer",
    "StorageScope",
    "TABLES_DIRNAME",
    "geographic_feature_files",
]
