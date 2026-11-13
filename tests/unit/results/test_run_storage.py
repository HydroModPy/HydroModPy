"""Storage of a run on disk: precision of stored fields, sentinels, versions of every document.

The file keeps the cross-module cases of the storage contract. Sections run from the
field store (float32 rounding, MODFLOW sentinels), through the version window of each
stored document, to mesh layout, ledgers and the stream-network sidecar.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import logging
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, get_args, get_origin

import duckdb
import numpy as np
import pandas as pd
import pytest
import zarr
from pydantic import BaseModel

import hydromodpy
import hydromodpy as hmp
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.session import open_session_dir
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.exceptions import (
    CatalogUnreadableError,
    ConfigMissingError,
    ExportError,
    IncompatibleMeshError,
    SchemaVersionMismatchError,
    WriteConflictError,
)
from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.core.fields.precision import KEPT_MANTISSA_BITS, MAX_RELATIVE_ERROR, round_mantissa
from hydromodpy.core.io.db_retry import connect_with_retry
from hydromodpy.core.io.document_version import (
    FOREIGN_REMEDY,
    NEWER_REMEDY,
    OLDER_REMEDY,
    VersionWindow,
    parse_version,
)
from hydromodpy.core.payload.index import (
    INSTALL_FILENAME,
    INSTALL_SCHEMA,
    InstallIndex,
    read_index,
    write_index,
)
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_SCHEMA,
    read_lockfile_meta,
    write_lockfile,
)
from hydromodpy.data.provenance.sidecars import Sidecar
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import FigureRequest
from hydromodpy.display.runs import draw_requests, figures_dir_of, regen_figures
from hydromodpy.display.theme import get_theme
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, FaceFamilyTable, PlanarCellMesh
from hydromodpy.project.launch.lease import LEASE_SCHEMA, acquire_lease, lease_path, read_lease
from hydromodpy.project.launch.plan import case_is_done, running_cases
from hydromodpy.project.launch.status import case_state, project_status
from hydromodpy.project.show import project_summary
from hydromodpy.results.annotations import (
    ANNOTATIONS_VERSION,
    Annotations,
    add_note,
    add_tag,
    read_annotations,
    remove_tag,
)
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.index_schema import (
    INDEX_META_TABLE,
    INDEX_SCHEMA_VERSION,
    META_SCHEMA_VERSION,
)
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.catalog.liveness import (
    ABANDONED_SESSION_MINUTES,
    abandoned_calibration_session_count,
)
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.results.exporters.request import (
    export_data_requests,
    regen_exports,
    run_export_target,
)
from hydromodpy.results.heartbeat import HEARTBEAT_SCHEMA, Heartbeat, heartbeat_path, read_heartbeat
from hydromodpy.results.identity import (
    IDENTITY_SCHEMA,
    MetaSidecar,
    meta_sidecar_path,
    read_identity_from,
)
from hydromodpy.results.ledger import LEDGER_SCHEMA, Ledger, LedgerEntry, ledger_path
from hydromodpy.results.outcome import OUTCOME_SCHEMA, Outcome, effective_status, read_outcome
from hydromodpy.results.plan_store import (
    PLAN_REMEDY,
    PLAN_SCHEMA,
    Plan,
    PlanCase,
    read_plan,
    write_plan,
)
from hydromodpy.results.publication import (
    PUBLICATION_SCHEMA,
    PUBLISHED_REMEDY,
    PUBLISHED_SCHEMA,
    Publication,
    PublicationSource,
    PublishedLine,
    append_published,
    publication_path,
    published_path,
    read_publication,
    read_published,
    write_publication,
)
from hydromodpy.results.record.checks import CHECKS_SCHEMA
from hydromodpy.results.record.manifest import (
    RUN_RECORD_MANIFEST_VERSION,
    ManifestRun,
    RunSeal,
    read_manifest,
    read_seal,
)
from hydromodpy.results.record.record import (
    INPUTS_SCHEMA,
    PROVENANCE_VERSION,
    InputsDocument,
    RunProvenance,
    RunRecord,
    read_inputs,
    read_provenance,
)
from hydromodpy.results.retention import RetentionPolicy, mark_aborted, plan_gc
from hydromodpy.results.run.sfr import sfr_reach_links
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.descriptor import (
    SESSION_SCHEMA,
    SessionDescriptor,
    find_session_dir,
    read_session,
    resolve_session_dir,
    session_descriptor_path,
)
from hydromodpy.results.session.journal import TRIAL_SCHEMA, TrialLine, read_trials, trials_path
from hydromodpy.results.session.phase import PHASE_SCHEMA, PhaseDescriptor, phase_dir, read_phase
from hydromodpy.results.storage.attempt import finish_attempt
from hydromodpy.results.storage.contract import (
    LEDGER_FILENAME,
    PLAN_FILENAME,
    RUN_ANNOTATIONS_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    RUN_PROVENANCE_FILENAME,
    SESSION_DESCRIPTOR_FILENAME,
)
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
from hydromodpy.results.storage.run_facts import (
    FACTS_SCHEMA,
    RunFacts,
    facts_path,
    read_facts,
    write_facts,
)
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed, sealed_solution_key
from hydromodpy.results.trash import identity_of
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.results.zarr_store.mesh_layout import mesh_layout_from_cell_mesh
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.schema.job.documents import read_versioned
from hydromodpy.schema.job.inputset import INPUTSET_VERSIONS
from hydromodpy.schema.job.outcome import OUTCOME_VERSIONS as JOB_OUTCOME_VERSIONS
from hydromodpy.schema.job.provenance import PROVENANCE_VERSIONS as JOB_PROVENANCE_VERSIONS
from hydromodpy.schema.job.seal import JOB_SEAL_V2_SCHEMA
from hydromodpy.solver.modflow6.extractors.flow import _reach_row
from hydromodpy.solver.modflow6.extractors.sfr import SfrObsSpec, SfrReachGeometry
from hydromodpy.workflow.record.journal import JOURNAL_SCHEMA, WorkflowJournal, journal_path
from hydromodpy.workflow.record.manifest import (
    RESOLVED_CONFIG_SCHEMA,
    ResolvedRunManifest,
    read_resolved_config,
    resolved_config_path,
    write_resolved_config,
)
from hydromodpy.workflow.record.manifest import SCHEMA_VERSION as RESOLVED_MANIFEST_SCHEMA
from hydromodpy.workflow.steps.data_description import SCHEMA_VERSION as LOADED_DATA_SCHEMA
from hydromodpy.workflow.steps.data_description import (
    describe_loaded_data,
    description_path,
    read_data_description,
    write_data_description,
)
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests._helpers.run_stores import claim_run, facts_of, open_run_store, seal_demo_run
from tests._helpers.sealed_runs import (
    NOW,
    VERSION,
    make_project,
    seal_run,
    write_attempt,
    write_session_dir,
)
from tests._helpers.ugrid_meshes import quad_mesh

# ``compact`` (the default) writes float32 rounded at 16 mantissa bits and says
# so with the CF-1.11 quantization attributes. ``exact`` writes float64, bit for
# bit. Geometry, static fields, indices and timestamps are never rounded, and
# every reader returns float64 whatever the store holds.
N_CELLS = 6
DROPPED_MASK = np.uint32((1 << (23 - KEPT_MANTISSA_BITS)) - 1)


def _values(n_steps: int = 4) -> np.ndarray:
    rng = np.random.default_rng(29)
    return 100.0 + rng.normal(size=(n_steps, 1, N_CELLS)) * 30.0


@pytest.fixture
def compact(tmp_path: Path):
    store = SimulationZarr.create(tmp_path / "compact.zarr", n_cells=N_CELLS, n_layers=1)
    yield store
    store.close()


def test_compact_stack_is_rounded_float32(compact: SimulationZarr) -> None:
    values = _values()

    compact.write_field_stack("head", values)

    stored = np.asarray(compact.root["head"][:])
    assert stored.dtype == np.float32
    assert not np.any(stored.view(np.uint32) & DROPPED_MASK)
    np.testing.assert_array_equal(stored, round_mantissa(values))
    np.testing.assert_allclose(stored, values, rtol=MAX_RELATIVE_ERROR, atol=0.0)


INTEGER_FIELDS = [
    pytest.param(np.array([[0, 1, 1, 0, 1, 0]], dtype="int8"), id="int8 mask"),
    pytest.param(np.array([[0, 1, 2, 3, 4, 5]], dtype="int32"), id="int32 counts"),
]


@pytest.mark.parametrize("values", INTEGER_FIELDS)
def test_integer_field_is_untouched(compact: SimulationZarr, values: np.ndarray) -> None:
    compact.write_field_stack("seepage_mask", values, subgroup="derived")

    array = compact.root["derived"]["seepage_mask"]
    assert array.dtype == values.dtype
    assert "quantization" not in dict(array.attrs)
    np.testing.assert_array_equal(np.asarray(array[:]), values)


def test_run_store_precision(tmp_path: Path) -> None:
    values = _values(2)
    for precision, dtype in (("compact", np.float32), ("exact", np.float64)):
        project = tmp_path / precision
        claim = claim_run(project, "run")
        persistence = PersistenceConfig(field_precision=precision)
        facts = facts_of(claim, project="p", n_cells=N_CELLS, n_layers=1, n_timesteps=2)
        with RunStore.open(
            claim.run_dir, facts=facts, persistence=persistence, workspace=project
        ) as store:
            store.create_zarr(n_cells=N_CELLS, n_layers=1)
            sid = store.sim_id
            store.write_field_stack(sid, "head", values)
            sz = store.open_zarr(sid)
            try:
                assert sz.field_precision == precision
                assert sz.root["head"].dtype == dtype
            finally:
                sz.close()
            read = store.query_field(sid, "head", 1)
            assert read.dtype == np.float64
            np.testing.assert_allclose(read, values[1], rtol=MAX_RELATIVE_ERROR, atol=0.0)


# A valid DuckDB file is written, closed, then truncated to half its size.
@pytest.fixture
def truncated_index(tmp_path: Path) -> Path:
    """A DuckDB file that opened fine once, now missing its back half."""
    index = tmp_path / "index.duckdb"
    connection = duckdb.connect(str(index))
    connection.execute("CREATE TABLE simulations (sim_id VARCHAR)")
    connection.close()

    size = index.stat().st_size
    with open(index, "r+b") as handle:
        handle.truncate(size // 2)

    return index


def test_truncated_index_is_refused(truncated_index: Path) -> None:
    with pytest.raises(CatalogUnreadableError, match="reindex"):
        connect_with_retry(str(truncated_index))


def test_two_open_modes_are_no_corruption(tmp_path: Path) -> None:
    # A read-only and a read-write open in one process is a mode conflict.
    index = tmp_path / "index.duckdb"
    first = duckdb.connect(str(index))
    first.execute("CREATE TABLE simulations (sim_id VARCHAR)")
    first.close()

    reader = connect_with_retry(str(index), read_only=True)
    try:
        with pytest.raises(WriteConflictError) as excinfo:
            connect_with_retry(str(index))
    finally:
        reader.close()

    assert "already open in this process" in str(excinfo.value)
    assert "reindex" not in str(excinfo.value)


# Every write entry point masks MODFLOW sentinels to NaN: per timestep, as a
# stack, or without a time axis.
HDRY = -1.0e30
HNOFLO = 1.0e30
MF_PACKAGE_DRY = -6.0e30


def test_sentinels_are_stored_as_nan(compact: SimulationZarr) -> None:
    values = np.array([[1.5, HDRY, HNOFLO, MF_PACKAGE_DRY, -2.5, 0.0]], dtype="float64")

    compact.write_field_stack("head", values)

    stored = np.asarray(compact.root["head"][:])
    assert np.isnan(stored[0, 1:4]).all()
    np.testing.assert_array_equal(stored[0, [0, 4, 5]], [1.5, -2.5, 0.0])


def test_every_write_path_masks(compact: SimulationZarr) -> None:
    sentinel_row = np.array([HNOFLO] * 6, dtype="float64")

    compact.write_field("head", 0, sentinel_row, n_timesteps=1)
    compact.write_field_stack("release_flux", sentinel_row[None, :], subgroup="derived")
    compact.write_static_field("hydraulic_conductivity", sentinel_row, subgroup="derived")

    assert np.isnan(np.asarray(compact.root["head"][:])).all()
    assert np.isnan(np.asarray(compact.root["derived"]["release_flux"][:])).all()
    assert np.isnan(np.asarray(compact.root["derived"]["hydraulic_conductivity"][:])).all()


def test_threshold_value_survives(compact: SimulationZarr) -> None:
    # The mask is a strict comparison: the threshold itself is kept.
    values = np.array(
        [[SENTINEL_ABS_THRESHOLD, -SENTINEL_ABS_THRESHOLD, SENTINEL_ABS_THRESHOLD * 1.1]],
        dtype="float64",
    )

    compact.write_field_stack("head", values, n_timesteps=1)

    stored = np.asarray(compact.root["head"][:], dtype="float64")
    # Kept, then rounded to the compact precision like any other value.
    np.testing.assert_allclose(
        stored[0, :2], [SENTINEL_ABS_THRESHOLD, -SENTINEL_ABS_THRESHOLD], rtol=MAX_RELATIVE_ERROR
    )
    assert np.isnan(stored[0, 2])


# A killed run leaves its ``session.json`` ``running`` for good. The project
# watchers count such a session from its descriptor, without the index.
LONG_AGO = datetime.now(UTC) - timedelta(minutes=ABANDONED_SESSION_MINUTES + 60)


def test_abandoned_session_is_counted(tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    write_session_dir(root, "lost", status="running", started_at=LONG_AGO)

    assert abandoned_calibration_session_count(root) == 1


# The rule is :mod:`hydromodpy.core.io.document_version`: a document HydroModPy
# writes on disk carries a ``schema`` id or an integer ``*_version``; its reader
# refuses a document outside the window of its family, or that carries no version,
# with :class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`. The message
# names the version read, the version that wrote it, what this code reads and what
# to do. Inside the window, a key or a word a later version added reads, and an
# unreadable document never stops a listing.
#
# The tree is written by the helpers of ``tests/_helpers`` and by the writers
# themselves: a sealed run, a running attempt, a session, a plan, a publication,
# the lease, the lockfile and the index.
#
# Exempt documents, and why:
#
# - ``README.md`` (run, session, summary, copy): a page for people, rendered
#   from the seal, never read back.
# - ``config.toml`` of a run and the case TOMLs of a plan: a configuration.
#   Its grammar is the one thing that is migrated, by
#   ``config/config_migration.py`` on load and ``hmp doctor --fix-config``.
# - ``plan/<hash>/cases.csv``: read only by
#   ``read_plan``, after ``plan.json``, whose schema versions the directory.
# - ``plan/current``: a pointer, the hash of a plan directory that carries its
#   version.
# - ``jobs/<stamp>/journal.jsonl`` and ``cases.txt``: the trace of one launch,
#   shown by ``hmp project log``. Nothing decides on it, and the journal of a
#   scheduler job is rebuilt from the ``outcome.json`` of its cases.
# - ``trash/tombstones.txt``: lines of three plain columns, ``rel_dir,sim_id,
#   date``, with no structure to version; a malformed line is refused by its
#   number.
# - ``summary/`` tables, page and RO-Crate: derived, written again whole by
#   ``hmp campaign collect`` (its ledgers ``index.json`` are versioned, below).
# - ``.hmp/identity_notice.json`` of a workspace: a memo of the warnings
#   already given; losing it repeats one warning.
# - ``request.json`` of a job and ``chain.json``: an input the caller writes, read
#   by its own validation, not a stored result.
WRITER = "2.0.0a1"


TRANSIENT = "It is transient state: delete it and run again."


LOCK = "hmp data lock"


REINDEX = "hmp catalog reindex"


RUN = "nancon_daily"


RUNNING = "nancon_running"


SESSION = "calage"


PHASE = "steady_k"


COPY = "copy"


RUN_ID = "a1b2c3d4-0000-4000-8000-000000000001"


@dataclass(frozen=True)
class Tree:
    """The project every case reads, and the places its documents live."""

    project: Path
    run: Path
    running: Path
    session: Path
    copy: Path
    lockfile: Path
    csv: Path


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Tree:
    """Write one of every stored document, once for the module."""
    project = make_project(tmp_path_factory.mktemp("documents") / "demo")
    seal_run(project, RUN, tags=("best",), hydromodpy_version=WRITER)
    run = project / "runs" / RUN
    running = write_attempt(project, f"runs/{RUNNING}", heartbeat_age_s=5.0)
    write_facts(
        running,
        RunFacts(
            sim_id=RUN_ID,
            name=RUNNING,
            case_id=RUNNING,
            project="demo",
            attempt=1,
            attempt_id="0" * 32,
            created_at=NOW,
            started_at=NOW,
        ),
    )
    WorkflowJournal(running).start_step(
        run_id=RUN_ID, step_order=1, step_name="setup", inputs_hash=None
    )
    write_data_description(running, RUN_ID, describe_loaded_data(None))
    write_resolved_config(running, RUN_ID, {"flow": {"K": 1e-5}})
    ResolvedRunManifest(
        schema_version=RESOLVED_MANIFEST_SCHEMA,
        run_id=RUN_ID,
        config_sha256=None,
        config_path=None,
        workspace=None,
        steps=("setup",),
        step_index=0,
        step_name="setup",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    ).write_atomic(running)
    write_session_dir(project, SESSION, phases=(PHASE,), best_trial=1)
    write_plan(
        project,
        Plan(plan_hash="0123abcd", hydromodpy_version=WRITER, created_at=NOW, n_cases=1),
        pd.DataFrame({"site": ["J0014010"]}, dtype=str),
        [PlanCase(case_id="J0014010-base", config_hash="h", config_path="J0014010-base.toml")],
        {"J0014010-base": "[flow]\nK = 1e-5\n"},
    )
    record = RunRecord.read(run)
    figure = run / RUN_FIGURES_DIRNAME / "heads.png"
    figure.parent.mkdir(parents=True, exist_ok=True)
    figure.write_bytes(b"png")
    Ledger(
        entries=[
            LedgerEntry(
                file="heads.png",
                producer="display.figures.heads",
                hydromodpy_version=WRITER,
                at=NOW,
                sha256="a" * 64,
                identity=record.identity,
            )
        ]
    ).write(figure.parent)
    csv = run / "exports" / "discharge.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text("date,q\n", encoding="utf-8")
    record.identity.write_meta_json(csv)
    copy = project.parent / COPY
    write_publication(
        copy,
        Publication(
            source=PublicationSource(project="demo", rel_dir=f"runs/{RUN}", sim_id=RUN_ID),
            hydromodpy_version=WRITER,
            published_at=NOW,
            format="dir",
        ),
    )
    append_published(
        run,
        PublishedLine(
            kind="copy", to=str(copy), format="dir", published_at=NOW, publication_sha256="b" * 64
        ),
    )
    write_index(copy, InstallIndex(hydromodpy_version=WRITER))
    acquire_lease(project)
    lockfile = project / LOCKFILE_NAME
    write_lockfile(lockfile, project / "data")
    rebuild_index(project)
    return Tree(
        project=project,
        run=run,
        running=running,
        session=project / "sessions" / SESSION,
        copy=copy,
        lockfile=lockfile,
        csv=csv,
    )


@pytest.fixture
def tree(pristine: Tree, tmp_path: Path) -> Tree:
    """A copy of the pristine tree that one case may damage."""
    import shutil

    root = tmp_path / "tree"
    shutil.copytree(pristine.project.parent, root, symlinks=True)

    def moved(path: Path) -> Path:
        return root / path.relative_to(pristine.project.parent)

    return Tree(
        project=moved(pristine.project),
        run=moved(pristine.run),
        running=moved(pristine.running),
        session=moved(pristine.session),
        copy=moved(pristine.copy),
        lockfile=moved(pristine.lockfile),
        csv=moved(pristine.csv),
    )


@dataclass(frozen=True)
class Document:
    """One stored document: where it is, what holds its version, who reads it."""

    name: str
    path: Callable[[Tree], Path]
    key: str
    version: object
    read: Callable[[Tree], object]
    remedy: str | None = None
    """What a document that can be written again says; ``None`` for a sealed one."""
    writer: str = WRITER
    """The version that wrote a sealed document."""
    kind: str = "json"


DOCUMENTS: tuple[Document, ...] = (
    Document(
        "manifest.json",
        lambda t: t.run / RUN_MANIFEST_FILENAME,
        "manifest_version",
        RUN_RECORD_MANIFEST_VERSION,
        lambda t: read_manifest(t.run),
    ),
    Document(
        "provenance.json",
        lambda t: t.run / RUN_PROVENANCE_FILENAME,
        "provenance_version",
        PROVENANCE_VERSION,
        lambda t: read_provenance(t.run),
    ),
    Document(
        "inputs.json",
        lambda t: t.run / RUN_INPUTS_FILENAME,
        "schema",
        INPUTS_SCHEMA,
        lambda t: read_inputs(t.run),
    ),
    Document(
        "outcome.json",
        lambda t: t.run / RUN_OUTCOME_FILENAME,
        "schema",
        OUTCOME_SCHEMA,
        lambda t: read_outcome(t.run),
    ),
    Document(
        "annotations.json",
        lambda t: t.run / RUN_ANNOTATIONS_FILENAME,
        "annotations_version",
        ANNOTATIONS_VERSION,
        lambda t: read_annotations(t.run),
    ),
    Document(
        "figures/index.json",
        lambda t: ledger_path(t.run / RUN_FIGURES_DIRNAME),
        "schema",
        LEDGER_SCHEMA,
        lambda t: Ledger.read(t.run / RUN_FIGURES_DIRNAME),
    ),
    Document(
        "<file>.meta.json",
        lambda t: meta_sidecar_path(t.csv),
        "schema",
        IDENTITY_SCHEMA,
        lambda t: read_identity_from(t.csv),
    ),
    Document(
        "published.jsonl",
        lambda t: published_path(t.run),
        "schema",
        PUBLISHED_SCHEMA,
        lambda t: read_published(t.run),
        kind="jsonl",
        remedy=PUBLISHED_REMEDY,
    ),
    Document(
        "logs/heartbeat.json",
        lambda t: heartbeat_path(t.running),
        "schema",
        HEARTBEAT_SCHEMA,
        lambda t: read_heartbeat(t.running),
        TRANSIENT,
    ),
    Document(
        ".hmp/checkpoints/facts.json",
        lambda t: facts_path(t.running),
        "schema",
        FACTS_SCHEMA,
        lambda t: read_facts(t.running),
        TRANSIENT,
    ),
    Document(
        ".hmp/checkpoints/steps.json",
        lambda t: journal_path(t.running),
        "schema",
        JOURNAL_SCHEMA,
        lambda t: WorkflowJournal(t.running).list_steps(RUN_ID),
        TRANSIENT,
    ),
    Document(
        ".hmp/checkpoints/loaded_data.json",
        lambda t: description_path(t.running),
        "schema",
        LOADED_DATA_SCHEMA,
        lambda t: read_data_description(t.running),
        TRANSIENT,
    ),
    Document(
        ".hmp/checkpoints/resolved_config.json",
        lambda t: resolved_config_path(t.running),
        "schema",
        RESOLVED_CONFIG_SCHEMA,
        lambda t: read_resolved_config(t.running),
        TRANSIENT,
    ),
    Document(
        ".hmp/checkpoints/resolved_manifest.json",
        lambda t: ResolvedRunManifest.path_for(t.running),
        "schema_version",
        RESOLVED_MANIFEST_SCHEMA,
        lambda t: ResolvedRunManifest.read(t.running),
        TRANSIENT,
    ),
    Document(
        "session.json",
        lambda t: session_descriptor_path(t.session),
        "schema",
        SESSION_SCHEMA,
        lambda t: read_session(t.session),
        writer=VERSION,
    ),
    Document(
        "phases/<p>/session.json",
        lambda t: phase_dir(t.session, PHASE) / SESSION_DESCRIPTOR_FILENAME,
        "schema",
        PHASE_SCHEMA,
        lambda t: read_phase(t.session, PHASE),
        writer=VERSION,
    ),
    Document(
        "trials.jsonl",
        lambda t: trials_path(t.session),
        "schema",
        TRIAL_SCHEMA,
        lambda t: read_trials(t.session),
        writer=VERSION,
        kind="jsonl",
    ),
    Document(
        "plan/<hash>/plan.json",
        lambda t: t.project / "plan" / "0123abcd" / PLAN_FILENAME,
        "schema",
        PLAN_SCHEMA,
        lambda t: read_plan(t.project),
        remedy=PLAN_REMEDY,
    ),
    Document(
        "PUBLICATION.json",
        lambda t: publication_path(t.copy),
        "schema",
        PUBLICATION_SCHEMA,
        lambda t: read_publication(t.copy),
    ),
    Document(
        "INSTALL.toml",
        lambda t: t.copy / INSTALL_FILENAME,
        "schema",
        INSTALL_SCHEMA,
        lambda t: read_index(t.copy),
        kind="toml",
    ),
    Document(
        ".hmp/launcher.lease",
        lambda t: lease_path(t.project),
        "schema",
        LEASE_SCHEMA,
        lambda t: read_lease(t.project),
        TRANSIENT,
    ),
    Document(
        "hydromodpy.lock",
        lambda t: t.lockfile,
        "schema",
        LOCKFILE_SCHEMA,
        lambda t: read_lockfile_meta(t.lockfile),
        LOCK,
        kind="toml",
    ),
    Document(
        ".hmp/index.duckdb",
        lambda t: catalog_path_for(t.project),
        "schema_version",
        INDEX_SCHEMA_VERSION,
        lambda t: Catalog(t.project),
        REINDEX,
        kind="index",
    ),
)


def _toml_line(document: Document) -> str:
    """Return the key of the line that holds the version in a TOML document (its last part)."""
    return document.key.rsplit(".", 1)[-1]


def _bumped(version: object) -> object:
    """Return a version this code does not know: one more, or the next schema id."""
    if isinstance(version, int):
        return version + 1
    text = str(version)
    match = re.search(r"(\d+)$", text)
    assert match is not None, text
    return f"{text[: match.start()]}{int(match.group(1)) + 1}"


def _stored(document: Document, tree: Tree) -> object:
    """Return the version the document carries on disk."""
    path = document.path(tree)
    if document.kind == "json":
        return json.loads(path.read_text(encoding="utf-8")).get(document.key)
    if document.kind == "jsonl":
        first = path.read_text(encoding="utf-8").splitlines()[0]
        return json.loads(first).get(document.key)
    if document.kind == "toml":
        line = _toml_line(document)
        match = re.search(rf'^{line} = "([^"]+)"', path.read_text(encoding="utf-8"), re.M)
        return None if match is None else match.group(1)
    connection = duckdb.connect(str(path), read_only=True)
    try:
        row = connection.execute(
            f"SELECT value FROM {INDEX_META_TABLE} WHERE key = ?", [META_SCHEMA_VERSION]
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else row[0]


def _rewrite(document: Document, tree: Tree, version: object | None) -> None:
    """Store *version* in the document, or remove its version when ``None``."""
    path = document.path(tree)

    def edit(payload: dict[str, Any]) -> dict[str, Any]:
        if version is None:
            payload.pop(document.key, None)
        else:
            payload[document.key] = version
        return payload

    if document.kind == "json":
        payload = edit(json.loads(path.read_text(encoding="utf-8")))
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif document.kind == "jsonl":
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[0] = json.dumps(edit(json.loads(lines[0])))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif document.kind == "toml":
        text = path.read_text(encoding="utf-8")
        line = _toml_line(document)
        replacement = "" if version is None else f'{line} = "{version}"'
        path.write_text(
            re.sub(rf'^{line} = "[^"]+"', replacement, text, count=1, flags=re.M),
            encoding="utf-8",
        )
    else:
        connection = duckdb.connect(str(path))
        try:
            if version is None:
                connection.execute(
                    f"DELETE FROM {INDEX_META_TABLE} WHERE key = ?", [META_SCHEMA_VERSION]
                )
            else:
                connection.execute(
                    f"UPDATE {INDEX_META_TABLE} SET value = ? WHERE key = ?",
                    [str(version), META_SCHEMA_VERSION],
                )
        finally:
            connection.close()


IDS = [document.name for document in DOCUMENTS]


@pytest.mark.parametrize("document", DOCUMENTS, ids=IDS)
def test_stored_version_is_the_read_one(document: Document, pristine: Tree) -> None:
    assert _stored(document, pristine) == document.version
    document.read(pristine)


SEALED_DOCUMENTS = [document for document in DOCUMENTS if document.remedy is None]
# The reader of the index rebuilds an index of another version instead of
# refusing it (tests/unit/results/test_reindex.py), so only the other
# documents are refused on their version.
REFUSED_DOCUMENTS = [document for document in DOCUMENTS if document.kind != "index"]


WINDOWS: dict[str, tuple[str, str]] = {
    "manifest.json": ("hydromodpy.results.record.manifest", "MANIFEST_VERSIONS"),
    "provenance.json": ("hydromodpy.results.record.record", "PROVENANCE_VERSIONS"),
    "inputs.json": ("hydromodpy.results.record.record", "INPUTS_VERSIONS"),
    "outcome.json": ("hydromodpy.results.outcome", "OUTCOME_VERSIONS"),
    "annotations.json": ("hydromodpy.results.annotations", "ANNOTATIONS_VERSIONS"),
    "figures/index.json": ("hydromodpy.results.ledger", "LEDGER_VERSIONS"),
    "<file>.meta.json": ("hydromodpy.results.identity", "IDENTITY_VERSIONS"),
    "published.jsonl": ("hydromodpy.results.publication", "PUBLISHED_VERSIONS"),
    "session.json": ("hydromodpy.results.session.descriptor", "SESSION_VERSIONS"),
    "phases/<p>/session.json": ("hydromodpy.results.session.phase", "PHASE_VERSIONS"),
    "trials.jsonl": ("hydromodpy.results.session.journal", "TRIAL_VERSIONS"),
    "PUBLICATION.json": ("hydromodpy.results.publication", "PUBLICATION_VERSIONS"),
    "INSTALL.toml": ("hydromodpy.core.payload.index", "INSTALL_VERSIONS"),
}


OTHER_WINDOWS: tuple[tuple[str, str, object], ...] = (
    ("hydromodpy.results.zarr_store.constants", "ZARR_VERSIONS", ZARR_SCHEMA_VERSION),
    ("hydromodpy.results.storage.parquet_schemas", "PARQUET_VERSIONS", PARQUET_SCHEMA_VERSION),
    ("hydromodpy.data.provenance.lockfile", "LOCKFILE_VERSIONS", LOCKFILE_SCHEMA),
    ("hydromodpy.results.record.checks", "CHECKS_VERSIONS", CHECKS_SCHEMA),
)


def _window_of(document: Document) -> VersionWindow:
    module, name = WINDOWS[document.name]
    return getattr(import_module(module), name)


def _reads(document: Document) -> str:
    """What the reader of *document* says it reads: its window, or its one version."""
    if document.name in WINDOWS:
        return _window_of(document).reads(document.key)
    return f"{document.key} = {document.version!r}"


def _oldest(document: Document) -> object:
    """The oldest version the reader of *document* reads; a run seal of a pre-release still reads."""
    if document.name in WINDOWS:
        return _window_of(document).oldest
    return document.version


def _older(version: object) -> object:
    """Return a version below the window: one less, or the previous schema id."""
    if isinstance(version, int):
        return version - 1
    text = str(version)
    match = re.search(r"(\d+)$", text)
    assert match is not None, text
    return f"{text[: match.start()]}{int(match.group(1)) - 1}"


@pytest.mark.parametrize("document", REFUSED_DOCUMENTS, ids=lambda document: document.name)
def test_newer_version_is_refused(document: Document, tree: Tree) -> None:
    bumped = _bumped(document.version)
    _rewrite(document, tree, bumped)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    message = str(refused.value)
    assert f"{document.key} = {bumped!r}" in message
    assert f"HydroModPy {HYDROMODPY_VERSION} reads {_reads(document)}" in message
    if document.remedy is None:
        assert NEWER_REMEDY in message
        assert f"written by HydroModPy {document.writer}" in message
    else:
        assert document.remedy in message


@pytest.mark.parametrize("document", SEALED_DOCUMENTS, ids=lambda document: document.name)
def test_older_version_is_refused(document: Document, tree: Tree) -> None:
    older = _older(_oldest(document))
    _rewrite(document, tree, older)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    assert f"{document.key} = {older!r}" in str(refused.value)
    # A trial.v1 line is refused by the one sentence of a pre-release, which names
    # the line; every other document by the remedy of a version below its window.
    remedy = "written by a pre-release" if document.name == "trials.jsonl" else OLDER_REMEDY
    assert remedy in str(refused.value)


@pytest.mark.parametrize("document", REFUSED_DOCUMENTS, ids=lambda document: document.name)
def test_missing_version_is_refused(document: Document, tree: Tree) -> None:
    _rewrite(document, tree, None)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    message = str(refused.value)
    assert f"carries no {document.key}" in message
    assert (document.remedy or OLDER_REMEDY) in message


@pytest.mark.parametrize("document", SEALED_DOCUMENTS, ids=lambda document: document.name)
def test_wider_window_is_read(
    document: Document, tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The day ``current`` moves up, a document at ``oldest`` is still read.
    module, name = WINDOWS[document.name]
    wider = VersionWindow(oldest=document.version, current=_bumped(document.version))
    monkeypatch.setattr(import_module(module), name, wider)

    document.read(tree)
    _rewrite(document, tree, wider.current)
    document.read(tree)


@pytest.mark.parametrize(
    ("module", "name", "current"),
    [
        *((module, name, None) for module, name in WINDOWS.values()),
        *OTHER_WINDOWS,
    ],
    ids=lambda value: value if isinstance(value, str) and value.isupper() else "",
)
def test_window_bounds(module: str, name: str, current: object) -> None:
    window = getattr(import_module(module), name)
    # The run seal reads the manifest_version 3 of a pre-release beside its own 4, and
    # the trial journal reads the trial.v2 lines of a pre-release beside its v3.
    oldest = {"MANIFEST_VERSIONS": 3, "TRIAL_VERSIONS": "hydromodpy.trial.v2"}.get(
        name, window.current
    )
    assert window.oldest == oldest
    assert current is None or window.current == current


@pytest.mark.parametrize("value", [None, True, 1.5, -1, "soon", "2.0.0a5", "", "1.2.3.4"])
def test_non_version_reads_as_older(value: object) -> None:
    assert parse_version(value) is None
    assert VersionWindow(oldest=2, current=2).standing(value) == "older"


def test_upside_down_window_refused() -> None:
    with pytest.raises(ValueError, match="not a window"):
        VersionWindow(oldest=3, current=2)


def test_newer_manifest_with_new_key_is_refused(tree: Tree) -> None:
    # The version decides first: an unknown key changes nothing to the refusal.
    target = tree.run / RUN_MANIFEST_FILENAME
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.update(manifest_version=RUN_RECORD_MANIFEST_VERSION + 1, new_block={"a": 1})
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaVersionMismatchError) as refused:
        RunRecord.read(tree.run)

    assert f"written by HydroModPy {WRITER}" in str(refused.value)
    assert NEWER_REMEDY in str(refused.value)


STORED_MODELS: tuple[type[BaseModel], ...] = (
    RunSeal,
    Outcome,
    RunProvenance,
    InputsDocument,
    Plan,
    PlanCase,
    SessionDescriptor,
    PhaseDescriptor,
    TrialLine,
    Publication,
    PublishedLine,
    Ledger,
    MetaSidecar,
    Annotations,
    RunFacts,
    Heartbeat,
    Sidecar,
)


def _closed_literals(annotation: Any) -> bool:
    if get_origin(annotation) is Literal:
        return True
    return any(_closed_literals(argument) for argument in get_args(annotation))


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for argument in get_args(annotation) for model in _nested_models(argument)]


def _models_reached() -> set[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    todo = list(STORED_MODELS)
    while todo:
        model = todo.pop()
        if model not in seen:
            seen.add(model)
            for field in model.model_fields.values():
                todo.extend(_nested_models(field.annotation))
    return seen


def test_no_closed_vocabulary() -> None:
    # A status, a kind or a regime is a string, so a later word still reads.
    closed = {
        f"{model.__name__}.{name}"
        for model in _models_reached()
        for name, field in model.model_fields.items()
        if _closed_literals(field.annotation)
    }
    # A seal certifies a completed run, and a run seal is the run profile of the
    # common seal: no later word can mean anything else for either.
    assert closed == {f"{ManifestRun.__name__}.status", f"{RunSeal.__name__}.profile"}


def test_stored_models_read_through_one_helper() -> None:
    # ``Model.model_validate`` would refuse what a later version added.
    names = {model.__name__ for model in _models_reached()}
    package = Path(hydromodpy.__file__).parent
    direct = [
        f"{path.relative_to(package)}:{node.lineno}"
        for path in package.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "model_validate"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in names
    ]
    assert direct == []


def _future_manifest(tree: Tree) -> None:
    document = next(item for item in DOCUMENTS if item.name == "manifest.json")
    _rewrite(document, tree, RUN_RECORD_MANIFEST_VERSION + 1)


def _refused_manifest(tree: Tree) -> None:
    """Store a manifest at the current version whose body its model refuses."""
    target = tree.run / RUN_MANIFEST_FILENAME
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.update(run="x", sealed_at="notadate")
    target.write_text(json.dumps(payload), encoding="utf-8")


def _older_field_store(tree: Tree) -> None:
    """Store a sealed run whose field store is below the window, its manifest still read."""
    target = tree.run / "fields.zarr" / "zarr.json"
    target.parent.mkdir(exist_ok=True)
    attributes = {"zarr_schema_version": "3", "hydromodpy_version": "2.0.0a5"}
    target.write_text(json.dumps({"attributes": attributes}), encoding="utf-8")


UNREADABLE_MANIFESTS = pytest.mark.parametrize(
    "spoil",
    [_future_manifest, _refused_manifest, _older_field_store],
    ids=["newer", "refused body", "older field store"],
)


def test_old_field_store_is_refused(tree: Tree, caplog: pytest.LogCaptureFixture) -> None:
    _older_field_store(tree)

    with pytest.raises(SchemaVersionMismatchError, match="pre-release .* must be run again"):
        hmp.open(tree.run)
    with caplog.at_level(logging.WARNING):
        report = rebuild_index(tree.project)

    assert [entry.rel_dir for entry in report.skipped] == [f"runs/{RUN}"]
    assert "must be run again" in report.skipped[0].reason
    assert any("index left out" in record.getMessage() for record in caplog.records)


def _future_session(tree: Tree) -> None:
    document = next(item for item in DOCUMENTS if item.name == "session.json")
    _rewrite(document, tree, _bumped(SESSION_SCHEMA))


def _solution_key(tree: Tree) -> str:
    return str(read_manifest(tree.run)["identity"]["solution_key"])


def _summary_of(tree: Tree) -> dict[str, Any]:
    return project_summary(tree.project)


RUN_LISTINGS: tuple[tuple[str, Callable[[Tree, str], Any], Any], ...] = (
    ("case_is_done", lambda t, h: case_is_done(t.project, RUN, h, "simulation"), False),
    ("effective_status", lambda t, h: effective_status(t.run), "unreadable"),
    ("case_state", lambda t, h: case_state(t.project, RUN).status, "planned"),
    ("running_cases", lambda t, h: running_cases(t.project, [RUN]), []),
    ("sealed_solution_key", lambda t, h: sealed_solution_key(t.run), None),
    ("project show", lambda t, h: _summary_of(t)["runs"].get("unreadable"), 1),
    (
        "gc plan",
        lambda t, h: (
            RUN_REL in plan_gc(t.project, RetentionPolicy(keep_versions=0), now=NOW).superseded_runs
        ),
        False,
    ),
)


RUN_REL = f"runs/{RUN}"


@UNREADABLE_MANIFESTS
@pytest.mark.parametrize(
    ("name", "ask", "answer"), RUN_LISTINGS, ids=[name for name, _ask, _answer in RUN_LISTINGS]
)
def test_listing_skips_unreadable_run(
    name: str,
    ask: Callable[[Tree, str], Any],
    answer: Any,
    spoil: Callable[[Tree], None],
    tree: Tree,
    caplog: pytest.LogCaptureFixture,
) -> None:
    solution_key = _solution_key(tree)
    assert case_is_done(tree.project, RUN, solution_key, "simulation")
    spoil(tree)

    with caplog.at_level(logging.WARNING):
        assert ask(tree, solution_key) == answer

    warned = [
        record
        for record in caplog.records
        if "is left out" in record.getMessage() and RUN in record.getMessage()
    ]
    assert warned or name == "running_cases"


def test_unreadable_outcome_is_skipped(tree: Tree) -> None:
    outcome = next(item for item in DOCUMENTS if item.name == "outcome.json")
    _rewrite(outcome, tree, _bumped(OUTCOME_SCHEMA))
    (tree.run / RUN_MANIFEST_FILENAME).unlink()

    assert effective_status(tree.run) == "unreadable"
    assert identity_of(tree.run) is None
    assert case_state(tree.project, RUN).status == "planned"


OUTCOMES_THAT_DO_NOT_READ = {
    "newer": lambda text: text.replace(OUTCOME_SCHEMA, str(_bumped(OUTCOME_SCHEMA))),
    "truncated": lambda text: text[:40],
    "not an object": lambda text: "[1, 2]",
}


@pytest.mark.parametrize(
    "spoil", OUTCOMES_THAT_DO_NOT_READ.values(), ids=OUTCOMES_THAT_DO_NOT_READ.keys()
)
def test_seal_stands_without_outcome(
    spoil: Callable[[str], str], tree: Tree, caplog: pytest.LogCaptureFixture
) -> None:
    # The run stays in every list, as completed, with one warning.
    target = tree.run / RUN_OUTCOME_FILENAME
    target.write_text(spoil(target.read_text(encoding="utf-8")), encoding="utf-8")
    seal = read_seal(tree.run)
    write_plan(
        tree.project,
        Plan(plan_hash="fedc3210", hydromodpy_version=WRITER, created_at=NOW, n_cases=1),
        pd.DataFrame({"site": ["J0014010"]}, dtype=str),
        [PlanCase(case_id=RUN, config_hash="h", config_path=f"{RUN}.toml")],
        {RUN: "[flow]\nK = 1e-5\n"},
    )

    with caplog.at_level(logging.WARNING):
        report = rebuild_index(tree.project)
        rows = project_status(tree.project).rows
        planned = plan_gc(tree.project, RetentionPolicy(keep_versions=0), now=NOW)
        tagged = add_tag(tree.run, "kept")

    assert RUN_REL in report.indexed
    with Catalog(tree.project) as catalog:
        case = catalog.cases.set_index("rel_dir").loc[RUN_REL]
    assert case["status"] == "completed" and case["sim_id"] == seal.run.sim_id
    assert case["attempt_id"] == seal.run.attempt_id
    assert case["host"] is None or pd.isna(case["host"])
    row = next(item for item in rows if item.case_id == RUN)
    assert (row.status, row.rel_dir, row.attempt) == ("completed", RUN_REL, seal.run.attempt)
    assert row.started_at == seal.run.started_at and row.host is None
    assert RUN_REL in planned.superseded_runs
    assert tagged.sim_id == seal.run.sim_id and identity_of(tree.run) == seal.run.sim_id
    warned = [
        record.getMessage() for record in caplog.records if str(target) in record.getMessage()
    ]
    assert len(warned) == 1 and "the seal stands" in warned[0]


def test_gc_age_limit_reads_the_seal(tree: Tree) -> None:
    (tree.run / RUN_OUTCOME_FILENAME).write_text("[]", encoding="utf-8")
    policy = RetentionPolicy(keep_versions=None, max_age_days=1)

    assert RUN_REL in plan_gc(tree.project, policy, now=NOW + timedelta(days=2)).expired_runs
    assert RUN_REL not in plan_gc(tree.project, policy, now=NOW).expired_runs


def test_unreadable_pulse_marks_attempt(tree: Tree) -> None:
    heartbeat = next(item for item in DOCUMENTS if item.name == "logs/heartbeat.json")
    _rewrite(heartbeat, tree, _bumped(HEARTBEAT_SCHEMA))

    assert effective_status(tree.running) == "unreadable"


def test_status_refuses_newer_plan(tree: Tree) -> None:
    plan = next(item for item in DOCUMENTS if item.name == "plan/<hash>/plan.json")
    _rewrite(plan, tree, _bumped(PLAN_SCHEMA))

    with pytest.raises(SchemaVersionMismatchError, match=re.escape(PLAN_REMEDY)):
        project_status(tree.project)


SESSION_LISTINGS: tuple[tuple[str, Callable[[Tree], Any], Any], ...] = (
    (
        "case_is_done",
        lambda t: case_is_done(t.project, SESSION, read_json_hash(t), "calibration"),
        False,
    ),
    ("case_state", lambda t: case_state(t.project, SESSION).status, "planned"),
    ("running_cases", lambda t: running_cases(t.project, [SESSION]), []),
    ("find_session_dir", lambda t: find_session_dir(t.project, read_json_id(t)), None),
    ("project show", lambda t: _summary_of(t)["sessions"].get("unreadable"), 1),
    ("abandoned", lambda t: abandoned_calibration_session_count(t.project), 0),
    ("identity_of", lambda t: identity_of(t.session), None),
)


def read_json_hash(tree: Tree) -> str:
    payload = json.loads(session_descriptor_path(tree.session).read_text(encoding="utf-8"))
    return str(payload["config_hash"])


def read_json_id(tree: Tree) -> str:
    payload = json.loads(session_descriptor_path(tree.session).read_text(encoding="utf-8"))
    return str(payload["session_id"])


@pytest.mark.parametrize(
    ("name", "ask", "answer"),
    SESSION_LISTINGS,
    ids=[name for name, _ask, _answer in SESSION_LISTINGS],
)
def test_listing_skips_unreadable_session(
    name: str, ask: Callable[[Tree], Any], answer: Any, tree: Tree
) -> None:
    _future_session(tree)
    (tree.session / RUN_OUTCOME_FILENAME).unlink(missing_ok=True)

    assert ask(tree) == answer


@pytest.mark.parametrize("name", ["phases/<p>/session.json", "trials.jsonl"])
def test_session_needs_phases_and_journal(name: str, tree: Tree) -> None:
    # Picking the latest session leaves it out, and naming it keeps the refusal.
    document = next(item for item in DOCUMENTS if item.name == name)
    _rewrite(document, tree, _bumped(document.version))

    with pytest.raises(ConfigMissingError, match="No readable calibration session"):
        resolve_session_dir(tree.project, None)
    write_session_dir(tree.project, "older", started_at=NOW - timedelta(days=1))
    assert resolve_session_dir(tree.project, None).name == "older"
    assert resolve_session_dir(tree.project, SESSION) == tree.session
    with pytest.raises(SchemaVersionMismatchError):
        document.read(tree)


def test_no_readable_session_refused(tree: Tree) -> None:
    _future_session(tree)

    with pytest.raises(ConfigMissingError, match="No readable calibration session"):
        resolve_session_dir(tree.project, None)


def test_resume_refuses_newer_session(tree: Tree) -> None:
    _future_session(tree)
    (tree.session / RUN_OUTCOME_FILENAME).unlink(missing_ok=True)
    directory, reopened = open_session_dir(tree.project, SESSION, resume=True)
    assert reopened and directory == tree.session

    with pytest.raises(SchemaVersionMismatchError, match=_bumped(SESSION_SCHEMA)):
        CalibrationPersistence(directory).resume_session()


JOB_MANIFEST_VERSIONS = VersionWindow(oldest=JOB_SEAL_V2_SCHEMA, current=JOB_SEAL_V2_SCHEMA)
"""The seal a job of a pre-release wrote, the only job manifest with a ``schema`` key."""

JOB_WINDOWS = [
    pytest.param(INPUTSET_VERSIONS, id="inputset"),
    pytest.param(JOB_PROVENANCE_VERSIONS, id="provenance"),
    pytest.param(JOB_OUTCOME_VERSIONS, id="outcome"),
    pytest.param(JOB_MANIFEST_VERSIONS, id="seal"),
]


@pytest.mark.parametrize("window", JOB_WINDOWS)
def test_job_document_refusals(window: VersionWindow, tmp_path: Path) -> None:
    target = tmp_path / "document.json"
    (tmp_path / "provenance.json").write_text(
        json.dumps({"tool": {"version": WRITER}}), encoding="utf-8"
    )
    for payload, remedy in (
        ({"schema": _bumped(window.current)}, NEWER_REMEDY),
        ({"schema": _older(window.current)}, OLDER_REMEDY),
        ({}, OLDER_REMEDY),
        ([], OLDER_REMEDY),
        ({"schema": "hmp-another/v1"}, FOREIGN_REMEDY),
    ):
        target.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SchemaVersionMismatchError) as refused:
            read_versioned(target, window)
        assert remedy in str(refused.value)
        assert f"written by HydroModPy {WRITER}" in str(refused.value)


# ``step_persist_mesh`` writes the geometry and the layout before the run. The solver
# extractors add the vertical part afterwards and never rewrite vertices or
# connectivity. A layout read back gives the families of the ``PlanarCellMesh`` it
# came from, and xugrid reads the stored edges as they are.
BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"


Z_INTERFACES = np.array([0.0, -10.0])


def _river_grid() -> PlanarCellMesh:
    """A 3 x 4 regular grid with a river chain and one lake face."""
    base = regular_cell_mesh(xmin=500000.0, ymin=6800000.0, dx=25.0, dy=25.0, nrow=3, ncol=4)
    geometry = base.geometry
    rank = int(np.flatnonzero((geometry.edge_cells == [5, 9]).all(axis=1))[0])
    table = FaceFamilyTable(
        names=("lakes",),
        family=[0],
        cell_a=[5],
        cell_b=[9],
        node_a=[geometry.edge_nodes[rank, 0]],
        node_b=[geometry.edge_nodes[rank, 1]],
        zone_left=[-1],
        zone_right=[-1],
    )
    chain = CellChain(family="rivers", chain_id=3, cell_ids=np.array([4, 5, 6, 7]))
    return dataclasses.replace(base, cell_chains=(chain,), face_families=table)


def _zoned_triangles() -> PlanarCellMesh:
    """The triangles of the bundle in two zones, split at the median x, with their contact faces."""
    base = bundle_triangles(BUNDLE)
    zone = (base.centers[:, 0] > np.median(base.centers[:, 0])).astype(np.int32)
    geometry = base.geometry
    cell_a, cell_b = geometry.edge_cells[:, 0], geometry.edge_cells[:, 1]
    contact = np.flatnonzero((cell_b >= 0) & (zone[cell_a] != zone[np.maximum(cell_b, 0)]))
    table = FaceFamilyTable(
        names=("geology",),
        family=np.zeros(contact.size),
        cell_a=cell_a[contact],
        cell_b=cell_b[contact],
        node_a=geometry.edge_nodes[contact, 0],
        node_b=geometry.edge_nodes[contact, 1],
        zone_left=zone[cell_a[contact]],
        zone_right=zone[cell_b[contact]],
    )
    return dataclasses.replace(
        base, cell_zone=zone, zone_names=("east", "west"), face_families=table
    )


def _vertices_3d(cell_mesh: PlanarCellMesh) -> np.ndarray:
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    return np.column_stack([xy, np.zeros(xy.shape[0])])


def _store(path: Path, cell_mesh: PlanarCellMesh, *, with_layout: bool = True) -> SimulationZarr:
    store = SimulationZarr.create(path, n_cells=cell_mesh.n_cells, n_layers=1)
    store.write_mesh(
        _vertices_3d(cell_mesh),
        cell_mesh.connectivity_rows,
        Z_INTERFACES,
        structured_shape=cell_mesh.structured_shape,
        layout=mesh_layout_from_cell_mesh(cell_mesh) if with_layout else None,
    )
    return store


def _members(group: zarr.Group) -> set[str]:
    return {name for name, _ in group.members()}


def test_mesh_group_attributes(tmp_path):
    cell_mesh = _river_grid()
    qa = {"p50": 1.0, "ratio": float("nan"), "far": float("inf"), "nested": {"v": np.float64(2.5)}}
    layout = mesh_layout_from_cell_mesh(
        cell_mesh, request_hash="ab12", qa=qa, library_versions={"shapely": "2.0.6"}
    )
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=cell_mesh.n_cells, n_layers=1)
    store.write_mesh(
        _vertices_3d(cell_mesh),
        cell_mesh.connectivity_rows,
        Z_INTERFACES,
        structured_shape=cell_mesh.structured_shape,
        layout=layout,
    )
    attrs = dict(store.root["mesh"].attrs)

    assert attrs["engine"] == "regular"
    assert attrs["engine_version"] == "0"
    assert attrs["crs"] == cell_mesh.crs_wkt
    assert attrs["mesh_request_hash"] == "ab12"
    assert attrs["library_versions"] == {"shapely": "2.0.6"}
    assert attrs["structured_shape"] == [3, 4]
    assert "engine_seed" not in attrs
    assert attrs["qa"] == {"p50": 1.0, "ratio": None, "far": None, "nested": {"v": 2.5}}
    store.close()
    json.loads((tmp_path / "fields.zarr" / "mesh" / "zarr.json").read_text(), parse_constant=_no)


def _no(token: str) -> None:
    raise AssertionError(f"the store holds the bare JSON token {token}")


def test_zone_names_are_stored(tmp_path):
    cell_mesh = _zoned_triangles()
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    zone = store.root["mesh"]["face_zone"]

    assert zone.attrs["zone_names"] == list(cell_mesh.zone_names)
    assert np.array_equal(zone[:], cell_mesh.cell_zone)
    store.close()


def test_foreign_layout_is_refused(tmp_path):
    cell_mesh = _river_grid()
    other = bundle_dual(BUNDLE)
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=cell_mesh.n_cells, n_layers=1)

    with pytest.raises(IncompatibleMeshError, match="cells"):
        store.write_mesh(
            _vertices_3d(cell_mesh),
            cell_mesh.connectivity_rows,
            Z_INTERFACES,
            layout=mesh_layout_from_cell_mesh(other),
        )
    store.close()


def test_topography_keeps_the_geometry(tmp_path):
    cell_mesh = _river_grid()
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    mesh = store.root["mesh"]
    vertices = mesh["vertices"][:]
    connectivity = mesh["face_node_connectivity"][:]
    n = cell_mesh.n_cells

    store.write_topography(
        np.linspace(10.0, 20.0, n),
        z_interfaces=np.array([0.0, -5.0, -9.0]),
        n_cells=n,
        n_layers=2,
        layer_thickness=np.full((2, n), 4.0),
        streambed_top=np.full(n, 9.0),
        streambed_connection=np.full(n, 1.0),
        grid_type="disv",
    )
    mesh = store.root["mesh"]

    assert {"topography", "layer_thickness", "streambed_top", "streambed_connection"} <= _members(
        mesh
    )
    assert mesh.attrs["grid_type"] == "disv"
    assert mesh.attrs["n_layers"] == 2
    assert mesh.attrs["engine"] == "regular"
    assert np.array_equal(mesh["vertices"][:], vertices)
    assert np.array_equal(mesh["face_node_connectivity"][:], connectivity)
    store.close()


# ``exports/index.json`` and ``figures/index.json`` name every derived file of a
# run with the options it was written with. Deleting the files and replaying
# the ledger writes the same files again, with the same entries and the same
# identity block. The exports replay on the store of the run, the index never
# opened; the figures replay on the run read through the catalog.
def _entries(directory) -> dict[str, tuple[str, dict, str | None]]:
    return {
        entry.file: (entry.producer, entry.options, entry.identity.sim_id)
        for entry in Ledger.read(directory).entries
    }


def test_export_ledger_replays(tmp_path, monkeypatch) -> None:
    run_dir, sim_id = seal_demo_run(tmp_path / "project")

    def refuse(*_args, **_kwargs):
        raise AssertionError("the export ledger replay opened the index")

    monkeypatch.setattr(Catalog, "__init__", refuse)
    requests = load_export_requests(
        [{"variables": "watershed"}, {"variables": "mesh_cell_area", "format": "geotiff"}]
    )
    with RunStore.open(run_dir) as store:
        written = export_data_requests(store, sim_id, requests)
        exports = run_dir / "exports"
        recorded = _entries(exports)
        for path in written:
            path.unlink()

        replayed = regen_exports(store, sim_id, run_export_target(store, sim_id))

    assert sorted(replayed) == sorted(written)
    assert _entries(exports) == recorded
    for path in replayed:
        identity = read_identity_from(path)
        assert identity is not None
        assert identity.sim_id == sim_id


def test_empty_export_ledger_refused(tmp_path) -> None:
    run_dir, sim_id = seal_demo_run(tmp_path / "project")

    with (
        RunStore.open(run_dir) as store,
        pytest.raises(ExportError, match="records no export to write again"),
    ):
        regen_exports(store, sim_id, run_export_target(store, sim_id))


def test_figure_ledger_replays(tmp_path) -> None:
    run_dir, sim_id = seal_demo_run(tmp_path / "project")
    figures = figures_dir_of(run_dir)
    with Catalog(tmp_path / "project") as catalog:
        run = catalog[sim_id]
        report = draw_requests(
            run,
            [FigureRequest(variable="head")],
            presets=PRESETS,
            theme=get_theme("default"),
            output_dir=figures,
        )
        assert report.written
        recorded = _entries(figures)
        for path in report.written:
            path.unlink()

        replayed = regen_figures(run, run_dir)

    assert sorted(replayed.written) == sorted(report.written)
    assert _entries(figures) == recorded
    for path in replayed.written:
        identity = read_identity_from(path)
        assert identity is not None
        assert identity.sim_id == sim_id


# The MODFLOW files are scratch, so a sealed run could say which cell carries a
# reach but not how the reaches connect. A profile along a branched network needs
# the connection: the numbering alone interleaves the tributaries.
REACH = {
    "ifno": 0,
    "layer": 0,
    "cell2d": 4,
    "rlen": 100.0,
    "rwid": 2.0,
    "rgrd": 0.01,
    "rtp": 150.0,
    "rbth": 1.0,
    "rhk": 1.0e-5,
    "manning": 0.035,
    "strahler": 1,
    "ustrf": 1.0,
}


def _links_of_sealed(project: Path, rows: list[dict] | None) -> pd.DataFrame:
    """Seal a run, with the ``sfr_reaches`` view when *rows* is given; read its links back."""
    store = open_run_store(project, "run", n_cells=1, n_layers=1)
    sid = store.sim_id
    if rows is not None:
        store.write_view(sid, "sfr_reaches", rows)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        return sfr_reach_links(Run(sid, catalog))


def test_sidecar_reads_downstream() -> None:
    reach = SfrReachGeometry.from_mapping({**REACH, "downstream": [2, 3]})

    assert reach.downstream == (2, 3)


def test_sidecar_without_links_refused() -> None:
    with pytest.raises(KeyError, match="downstream"):
        SfrObsSpec.from_mapping(
            {
                "obs_csv": "m.sfr.obs.csv",
                "network_id": "main",
                "reaches": [REACH],
            }
        )


def test_reach_row_numbering() -> None:
    reach = SfrReachGeometry.from_mapping({**REACH, "ifno": 2, "downstream": [3, 4]})

    row = _reach_row("main", reach)

    assert (row["reach_id"], row["reach"], row["downstream"]) == ("main:3", 3, [4, 5])
    assert "ifno" not in row


def test_no_network_no_links(tmp_path: Path) -> None:
    links = _links_of_sealed(tmp_path / "project", None)

    assert links.empty
    assert list(links.columns) == [
        "reach_id",
        "network_id",
        "reach",
        "rlen",
        "ustrf",
        "downstream",
    ]


_DAYS = np.array(
    ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"],
    dtype="datetime64[ns]",
)
_T, _N = 5, 3

_SERIES = {
    "etr": (
        np.full((_T, _N), 1.0),
        "mm/day",
        "time: mean",
        "Actual evapotranspiration of the soil",
    ),
    "recharge": (
        np.full((_T, _N), 2.0),
        "mm/day",
        "time: mean",
        "Recharge sent to the water table",
    ),
    "soil_storage": (
        np.full((_T, _N), 3.0),
        "mm",
        "time: point",
        "Soil water storage at the end of the day",
    ),
}


_COLUMNS = {
    "cell_index": np.array([0, 1, 2], dtype="int32"),
    "class_index": np.array([0, 0, 0], dtype="int32"),
    "x": np.array([0.0, 100.0, 200.0]),
    "y": np.array([0.0, 0.0, 0.0]),
    "ru_mm": np.array([120.0, 150.0, 100.0]),
    "cell_fraction": np.array([1.0, 1.0, 1.0]),
    "basin_weight": np.array([1 / 3, 1 / 3, 1 / 3]),
}


_ATTRS = {
    "source": "soil_reservoir",
    "crs": "EPSG:2154",
    "ru_mm": 120.0,
    "alpha": 0.6,
    "kc": 1.0,
    "impervious_fraction": 0.0,
    "bypass_fraction": 0.0,
    "transit_time_days": 0.0,
    "spinup": "first_year",
    "spinup_cycles": 2,
    "never_full_columns": 0,
    "n_cells": 3,
    "n_columns": 3,
}


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "sim.zarr"
    sz = SimulationZarr.create(path, n_cells=4, n_layers=1)
    sz.write_soil_columns(timestamps=_DAYS, series=_SERIES, columns=_COLUMNS, attrs=_ATTRS)
    sz.close()
    return path


def test_series_units_and_methods(tmp_path: Path) -> None:
    path = _write(tmp_path)
    sz = SimulationZarr(path)
    try:
        soil = sz.root["forcing"]["soil"]
        assert dict(soil["etr"].attrs)["units"] == "mm/day"
        assert dict(soil["etr"].attrs)["cell_methods"] == "time: mean"
        assert dict(soil["soil_storage"].attrs)["units"] == "mm"
        assert dict(soil["soil_storage"].attrs)["cell_methods"] == "time: point"
        assert dict(soil["ru_mm"].attrs)["units"] == "mm"
        assert dict(soil["cell_index"].attrs)["units"] == "1"
    finally:
        sz.close()


INTERFACES = np.array(
    [
        [10.0, 11.0, 12.0, 13.0],
        [6.0, 6.5, 7.0, 7.5],
        [0.0, 1.0, 2.0, 3.0],
    ]
)


IDOMAIN = np.array([[1, 0, 1, 1], [1, 1, -1, 1]])


@pytest.fixture
def store(tmp_path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=4, n_layers=2)
    vertices, connectivity = quad_mesh(2, 2)
    handle.write_mesh(vertices, connectivity, INTERFACES)
    yield handle
    handle.close()


def test_bad_idomain_refused(store) -> None:
    with pytest.raises(ValueError, match="only -1, 0 and 1"):
        store.write_topography(INTERFACES[0], idomain=IDOMAIN * 2)


def test_bad_interfaces_refused(store) -> None:
    with pytest.raises(IncompatibleMeshError, match="3 cells"):
        store.write_topography(INTERFACES[0], z_interfaces=INTERFACES[:, :3])
