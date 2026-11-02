"""Every stored document carries its version, and every reader reads a window of them.

The rule is :mod:`hydromodpy.core.io.document_version`: a document HydroModPy
writes on disk carries a ``schema`` id or an integer ``*_version``; its reader
refuses a document outside the window of its family, or that carries no version,
with :class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`. The message
names the version read, the version that wrote it, what this code reads and what
to do. Inside the window, a key or a word a later version added reads, and an
unreadable document never stops a listing.

The tree is written by the helpers of ``tests/_helpers`` and by the writers
themselves: a sealed run, a running attempt, a session, a plan, a publication,
the lease, the lockfile and the index.

Exempt documents, and why:

- ``README.md`` (run, session, summary, copy): a page for people, rendered
  from the seal, never read back.
- ``config.toml`` of a run and the case TOMLs of a plan: a configuration.
  Its grammar is the one thing that is migrated, by
  ``config/config_migration.py`` on load and ``hmp doctor --fix-config``.
- ``plan/<hash>/sites.parquet`` and ``cases.parquet``: read only by
  ``read_plan``, after ``plan.json``, whose schema versions the directory.
- ``plan/current``: a pointer, the hash of a plan directory that carries its
  version.
- ``jobs/<stamp>/journal.jsonl`` and ``cases.txt``: the trace of one launch,
  shown by ``hmp project log``. Nothing decides on it, and the journal of a
  scheduler job is rebuilt from the ``outcome.json`` of its cases.
- ``trash/tombstones.txt``: lines of three plain columns, ``rel_dir,sim_id,
  date``, with no structure to version; a malformed line is refused by its
  number.
- ``summary/`` tables, page and RO-Crate: derived, written again whole by
  ``hmp project collect`` (its ledgers ``index.json`` are versioned, below).
- ``.hmp/identity_notice.json`` of a workspace: a memo of the warnings
  already given; losing it repeats one warning.
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import BaseModel, ValidationError

import hydromodpy
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.session import open_session_dir
from hydromodpy.cli._workers.catalog import abandoned_calibration_session_count
from hydromodpy.cli.commands.project.show import _summary
from hydromodpy.config.sites.expansion import case_is_done
from hydromodpy.config.sites.plan import running_cases
from hydromodpy.core.exceptions import ConfigMissingError, SchemaVersionMismatchError
from hydromodpy.core.io.document_version import (
    FOREIGN_REMEDY,
    NEWER_REMEDY,
    OLDER_REMEDY,
    VersionWindow,
    parse_version,
)
from hydromodpy.core.payload import (
    INSTALL_FILENAME,
    INSTALL_SCHEMA,
    InstallIndex,
    read_index,
    write_index,
)
from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_VERSION,
    read_lockfile_meta,
)
from hydromodpy.data.provenance.sidecars import Sidecar
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.registry.freeze import write_lockfile
from hydromodpy.project.launch.lease import LEASE_SCHEMA, acquire_lease, lease_path, read_lease
from hydromodpy.project.launch.status import case_state
from hydromodpy.results.annotations import ANNOTATIONS_VERSION, Annotations, read_annotations
from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.catalog.index_schema import (
    INDEX_META_TABLE,
    INDEX_SCHEMA_VERSION,
    META_SCHEMA_VERSION,
)
from hydromodpy.results.heartbeat import (
    HEARTBEAT_SCHEMA,
    Heartbeat,
    heartbeat_path,
    read_heartbeat,
)
from hydromodpy.results.identity import (
    IDENTITY_SCHEMA,
    MetaSidecar,
    meta_sidecar_path,
    read_identity_from,
)
from hydromodpy.results.ledger import LEDGER_SCHEMA, Ledger, LedgerEntry, ledger_path
from hydromodpy.results.manifest import (
    RUN_RECORD_MANIFEST_VERSION,
    Manifest,
    ManifestRun,
    read_manifest,
)
from hydromodpy.results.outcome import OUTCOME_SCHEMA, Outcome, effective_status, read_outcome
from hydromodpy.results.plan_store import PLAN_SCHEMA, Plan, PlanCase, read_plan, write_plan
from hydromodpy.results.publication import (
    PUBLICATION_SCHEMA,
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
from hydromodpy.results.record import (
    INPUTS_SCHEMA,
    InputsDocument,
    RunProvenance,
    RunRecord,
    read_inputs,
    read_provenance,
)
from hydromodpy.results.retention import RetentionPolicy, plan_gc
from hydromodpy.results.session.descriptor import (
    SESSION_SCHEMA,
    SessionDescriptor,
    find_session_dir,
    read_session,
    resolve_session_dir,
    session_descriptor_path,
)
from hydromodpy.results.session.journal import TRIAL_SCHEMA, TrialLine, read_trials, trials_path
from hydromodpy.results.session.phase import (
    PHASE_SCHEMA,
    PhaseDescriptor,
    phase_dir,
    read_phase,
)
from hydromodpy.results.storage.attempt import claim_run_directory
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
from hydromodpy.results.storage.json_io import readable, readable_documents
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
from hydromodpy.results.storage.run_facts import (
    FACTS_SCHEMA,
    RunFacts,
    facts_path,
    read_facts,
    write_facts,
)
from hydromodpy.results.storage.sealing import sealed_config_hash
from hydromodpy.results.trash import identity_of, is_protected
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.workflow.internals.data_description import (
    SCHEMA_VERSION as LOADED_DATA_SCHEMA,
)
from hydromodpy.workflow.internals.data_description import (
    describe_loaded_data,
    description_path,
    read_data_description,
    write_data_description,
)
from hydromodpy.workflow.internals.manifest import (
    RESOLVED_CONFIG_SCHEMA,
    ResolvedRunManifest,
    read_resolved_config,
    resolved_config_path,
    write_resolved_config,
)
from hydromodpy.workflow.internals.manifest import SCHEMA_VERSION as RESOLVED_MANIFEST_SCHEMA
from hydromodpy.workflow.tracking.journal import JOURNAL_SCHEMA, WorkflowJournal, journal_path
from tests._helpers.sealed_runs import (
    NOW,
    VERSION,
    make_project,
    seal_run,
    write_attempt,
    write_session_dir,
)

WRITER = "2.0.0a1"
"""The version that wrote the run, the plan and the copy: not the one that reads them."""

TRANSIENT = "It is transient state: delete it and run again."
LOCK = "hmp dev lock update"
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
        pa.table({"site": ["J0014010"]}),
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
        PublishedLine(to=str(copy), format="dir", published_at=NOW, publication_sha256="b" * 64),
    )
    write_index(copy, InstallIndex(hydromodpy_version=WRITER))
    acquire_lease(project)
    catalog = DataCatalogDuckDB(project / "data" / "cache.duckdb")
    lockfile = project / LOCKFILE_NAME
    write_lockfile(
        catalog,
        lockfile,
        zarr_schema_version=ZARR_SCHEMA_VERSION,
        parquet_schema_version=PARQUET_SCHEMA_VERSION,
    )
    catalog.close()
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
        RUN_RECORD_MANIFEST_VERSION,
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
        "hydromodpy.version",
        LOCKFILE_VERSION,
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
def test_the_document_carries_the_version_its_reader_reads(
    document: Document, pristine: Tree
) -> None:
    assert _stored(document, pristine) == document.version
    document.read(pristine)


SEALED_DOCUMENTS = [document for document in DOCUMENTS if document.remedy is None]
"""The documents that cannot be written again: a window, not one exact version."""

WINDOWS: dict[str, tuple[str, str]] = {
    "manifest.json": ("hydromodpy.results.manifest", "MANIFEST_VERSIONS"),
    "provenance.json": ("hydromodpy.results.record", "PROVENANCE_VERSIONS"),
    "inputs.json": ("hydromodpy.results.record", "INPUTS_VERSIONS"),
    "outcome.json": ("hydromodpy.results.outcome", "OUTCOME_VERSIONS"),
    "annotations.json": ("hydromodpy.results.annotations", "ANNOTATIONS_VERSIONS"),
    "figures/index.json": ("hydromodpy.results.ledger", "LEDGER_VERSIONS"),
    "<file>.meta.json": ("hydromodpy.results.identity", "IDENTITY_VERSIONS"),
    "published.jsonl": ("hydromodpy.results.publication", "PUBLISHED_VERSIONS"),
    "session.json": ("hydromodpy.results.session.descriptor", "SESSION_VERSIONS"),
    "phases/<p>/session.json": ("hydromodpy.results.session.phase", "PHASE_VERSIONS"),
    "trials.jsonl": ("hydromodpy.results.session.journal", "TRIAL_VERSIONS"),
    "plan/<hash>/plan.json": ("hydromodpy.results.plan_store", "PLAN_VERSIONS"),
    "PUBLICATION.json": ("hydromodpy.results.publication", "PUBLICATION_VERSIONS"),
    "INSTALL.toml": ("hydromodpy.core.payload.index", "INSTALL_VERSIONS"),
}
"""Where each sealed document of the table declares its window."""

OTHER_WINDOWS: tuple[tuple[str, str, object], ...] = (
    ("hydromodpy.results.zarr_store.constants", "ZARR_VERSIONS", ZARR_SCHEMA_VERSION),
    ("hydromodpy.results.storage.parquet_schemas", "PARQUET_VERSIONS", PARQUET_SCHEMA_VERSION),
    ("hydromodpy.data.provenance.lockfile", "LOCKFILE_VERSIONS", LOCKFILE_VERSION),
    ("hydromodpy.results.checks", "CHECKS_VERSIONS", "hydromodpy.checks.v1"),
)


def _window_of(document: Document) -> VersionWindow:
    module, name = WINDOWS[document.name]
    return getattr(import_module(module), name)


def _older(version: object) -> object:
    """Return a version below the window: one less, or the previous schema id."""
    if isinstance(version, int):
        return version - 1
    text = str(version)
    match = re.search(r"(\d+)$", text)
    assert match is not None, text
    return f"{text[: match.start()]}{int(match.group(1)) - 1}"


@pytest.mark.parametrize("document", DOCUMENTS, ids=IDS)
def test_a_version_above_what_the_reader_reads_is_refused_naming_its_writer(
    document: Document, tree: Tree
) -> None:
    bumped = _bumped(document.version)
    _rewrite(document, tree, bumped)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    message = str(refused.value)
    assert f"{document.key} = {bumped!r}" in message
    assert f"HydroModPy {HYDROMODPY_VERSION} reads {document.key} = {document.version!r}" in message
    if document.remedy is None:
        assert NEWER_REMEDY in message
        assert f"written by HydroModPy {document.writer}" in message
    else:
        assert document.remedy in message


@pytest.mark.parametrize("document", SEALED_DOCUMENTS, ids=lambda document: document.name)
def test_a_version_below_the_window_says_a_pre_release_wrote_it(
    document: Document, tree: Tree
) -> None:
    older = _older(document.version)
    _rewrite(document, tree, older)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    assert f"{document.key} = {older!r}" in str(refused.value)
    assert OLDER_REMEDY in str(refused.value)


@pytest.mark.parametrize("document", DOCUMENTS, ids=IDS)
def test_a_document_without_its_version_is_refused_by_name(document: Document, tree: Tree) -> None:
    _rewrite(document, tree, None)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    message = str(refused.value)
    assert f"carries no {document.key}" in message
    assert (document.remedy or OLDER_REMEDY) in message


@pytest.mark.parametrize("document", SEALED_DOCUMENTS, ids=lambda document: document.name)
def test_every_version_of_a_wider_window_is_read(
    document: Document, tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The day ``current`` moves up, a document at ``oldest`` is still read."""
    module, name = WINDOWS[document.name]
    wider = VersionWindow(oldest=document.version, current=_bumped(document.version))
    monkeypatch.setattr(import_module(module), name, wider)

    document.read(tree)
    _rewrite(document, tree, wider.current)
    document.read(tree)


def test_a_document_of_another_family_is_refused_as_such(tree: Tree) -> None:
    outcome = next(document for document in DOCUMENTS if document.name == "outcome.json")
    _rewrite(outcome, tree, "hydromodpy.plan.v1")

    with pytest.raises(SchemaVersionMismatchError, match=FOREIGN_REMEDY):
        outcome.read(tree)


@pytest.mark.parametrize(
    ("module", "name", "current"),
    [
        *((module, name, None) for module, name in WINDOWS.values()),
        *OTHER_WINDOWS,
    ],
    ids=lambda value: value if isinstance(value, str) and value.isupper() else "",
)
def test_every_family_declares_both_bounds_and_they_are_equal_at_2_0_0(
    module: str, name: str, current: object
) -> None:
    window = getattr(import_module(module), name)
    assert window.oldest == window.current
    assert current is None or window.current == current


@pytest.mark.parametrize(
    ("value", "number"),
    [
        (2, (2, 0, 0)),
        ("3", (3, 0, 0)),
        ("v2", (2, 0, 0)),
        ("hydromodpy.session.v3", (3, 0, 0)),
        ("2.0.0", (2, 0, 0)),
        ("2.1", (2, 1, 0)),
    ],
)
def test_one_parser_reads_every_form_a_version_takes(value: object, number: tuple) -> None:
    parsed = parse_version(value)
    assert parsed is not None and parsed[1] == number


@pytest.mark.parametrize("value", [None, True, 1.5, -1, "soon", "2.0.0a5", "", "1.2.3.4"])
def test_a_value_that_is_no_version_reads_as_below_the_window(value: object) -> None:
    assert parse_version(value) is None
    assert VersionWindow(oldest=2, current=2).standing(value) == "older"


def test_a_window_upside_down_is_refused() -> None:
    with pytest.raises(ValueError, match="not a window"):
        VersionWindow(oldest=3, current=2)


# -- What a later version added ------------------------------------------------

FUTURE_KEYS: tuple[tuple[str, tuple[tuple[Any, ...], ...]], ...] = (
    (
        "manifest.json",
        (
            (),
            ("run",),
            ("site",),
            ("geometry",),
            ("period",),
            ("config",),
            ("lineage",),
            ("identity",),
            ("checks",),
            ("metrics", 0),
            ("parameters", 0),
        ),
    ),
    ("provenance.json", ((),)),
    ("inputs.json", ((),)),
    ("outcome.json", ((),)),
    ("annotations.json", ((),)),
    ("figures/index.json", ((), ("entries", 0), ("entries", 0, "identity"))),
    ("<file>.meta.json", ((), ("identity",))),
    ("session.json", ((), ("best",))),
    ("phases/<p>/session.json", ((),)),
    ("plan/<hash>/plan.json", ((),)),
    ("PUBLICATION.json", ((), ("source",))),
)
"""Where a later version may add a key, in each JSON document: the root and nested models."""


def _nested(payload: Any, path: tuple[Any, ...]) -> Any:
    for step in path:
        payload = payload[step]
    return payload


@pytest.mark.parametrize(("name", "paths"), FUTURE_KEYS, ids=[name for name, _paths in FUTURE_KEYS])
def test_a_future_key_at_the_current_version_reads(
    name: str, paths: tuple[tuple[Any, ...], ...], tree: Tree
) -> None:
    document = next(item for item in DOCUMENTS if item.name == name)
    target = document.path(tree)
    payload = json.loads(target.read_text(encoding="utf-8"))
    for path in paths:
        _nested(payload, path)["added_by_a_later_version"] = {"any": 1}
    target.write_text(json.dumps(payload), encoding="utf-8")

    document.read(tree)


@pytest.mark.parametrize("name", ["trials.jsonl", "published.jsonl"])
def test_a_future_key_on_a_line_of_a_journal_reads(name: str, tree: Tree) -> None:
    document = next(item for item in DOCUMENTS if item.name == name)
    target = document.path(tree)
    lines = target.read_text(encoding="utf-8").splitlines()
    lines[0] = json.dumps({**json.loads(lines[0]), "added_by_a_later_version": 1})
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    document.read(tree)


def test_a_future_manifest_with_a_higher_version_and_a_new_key_is_refused(tree: Tree) -> None:
    """The version decides first: a key the code does not know changes nothing to the refusal."""
    target = tree.run / RUN_MANIFEST_FILENAME
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload.update(manifest_version=RUN_RECORD_MANIFEST_VERSION + 1, new_block={"a": 1})
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaVersionMismatchError) as refused:
        RunRecord.read(tree.run)

    assert f"written by HydroModPy {WRITER}" in str(refused.value)
    assert NEWER_REMEDY in str(refused.value)


STORED_WORDS: tuple[tuple[str, tuple[Any, ...], Callable[[Tree], Any]], ...] = (
    ("session.json", ("status",), lambda t: read_session(t.session).status),
    ("phases/<p>/session.json", ("status",), lambda t: read_phase(t.session, PHASE).status),
    ("outcome.json", ("written_by",), lambda t: read_outcome(t.run).written_by),
    ("outcome.json", ("status",), lambda t: read_outcome(t.run).status),
    ("manifest.json", ("run", "flow_regime"), lambda t: RunRecord.read(t.run).run.flow_regime),
    (
        "manifest.json",
        ("geometry", "mesh_topology"),
        lambda t: RunRecord.read(t.run).geometry.mesh_topology,
    ),
    ("manifest.json", ("lineage", "kind"), lambda t: RunRecord.read(t.run).lineage.kind),
    (
        "manifest.json",
        ("parameters", 0, "origin"),
        lambda t: RunRecord.read(t.run).parameters[0].origin,
    ),
    ("PUBLICATION.json", ("format",), lambda t: read_publication(t.copy).format),
    ("PUBLICATION.json", ("label",), lambda t: read_publication(t.copy).label),
)
"""A stored field that can grow, and how a reader gets it back."""


@pytest.mark.parametrize(
    ("name", "path", "read"),
    STORED_WORDS,
    ids=[f"{name}:{path[-1]}" for name, path, _read in STORED_WORDS],
)
def test_a_word_a_later_version_wrote_is_read_back(
    name: str, path: tuple[Any, ...], read: Callable[[Tree], Any], tree: Tree
) -> None:
    document = next(item for item in DOCUMENTS if item.name == name)
    target = document.path(tree)
    payload = json.loads(target.read_text(encoding="utf-8"))
    _nested(payload, path[:-1])[path[-1]] = "a_later_word"
    target.write_text(json.dumps(payload), encoding="utf-8")

    assert read(tree) == "a_later_word"


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda t, word: read_session(t.session).model_dump(by_alias=True), "status"),
        (lambda t, word: read_outcome(t.run).model_dump(by_alias=True), "written_by"),
    ],
)
def test_a_word_outside_the_vocabulary_is_refused_when_written(
    build: Callable[[Tree, str], dict[str, Any]], field: str, pristine: Tree
) -> None:
    model = SessionDescriptor if field == "status" else Outcome
    payload = build(pristine, "a_later_word")
    with pytest.raises(ValidationError, match="is not one of"):
        model(**{**payload, field: "a_later_word"})


def test_the_index_keeps_the_words_a_later_version_wrote(tree: Tree) -> None:
    descriptor = session_descriptor_path(tree.session)
    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    descriptor.write_text(json.dumps({**payload, "status": "a_later_status"}), encoding="utf-8")
    snapshot = tree.run / "tables.parquet" / "simulation.parquet"
    table = pq.read_table(snapshot)
    for column, word in (("flow_regime", "a_later_regime"), ("mesh_topology", "a_later_mesh")):
        position = table.schema.get_field_index(column)
        table = table.set_column(position, column, pa.array([word], type=pa.string()))
    pq.write_table(table, snapshot)

    report = rebuild_index(tree.project)

    assert report.skipped == ()
    connection = duckdb.connect(str(catalog_path_for(tree.project)), read_only=True)
    try:
        assert connection.execute("SELECT code FROM flow_regimes WHERE id > 3").fetchall() == [
            ("a_later_regime",)
        ]
        assert connection.execute("SELECT status FROM cases WHERE kind = 'session'").fetchall() == [
            ("a_later_status",)
        ]
    finally:
        connection.close()


STORED_MODELS: tuple[type[BaseModel], ...] = (
    Manifest,
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
"""Every model a stored document is read into; the walk below reaches what they nest."""


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


def test_no_stored_model_holds_a_closed_vocabulary() -> None:
    """A status, a kind or a regime is a string with its words, so a later word reads."""
    closed = {
        f"{model.__name__}.{name}"
        for model in _models_reached()
        for name, field in model.model_fields.items()
        if _closed_literals(field.annotation)
    }
    # A seal certifies a completed run: no later word can mean anything else.
    assert closed == {f"{ManifestRun.__name__}.status"}


def test_every_read_of_a_stored_model_goes_through_the_one_helper() -> None:
    """``Model.model_validate`` on a stored model would refuse what a later version added."""
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


# -- A listing with one unreadable document ------------------------------------


def _future_manifest(tree: Tree) -> None:
    document = next(item for item in DOCUMENTS if item.name == "manifest.json")
    _rewrite(document, tree, RUN_RECORD_MANIFEST_VERSION + 1)


def _future_session(tree: Tree) -> None:
    document = next(item for item in DOCUMENTS if item.name == "session.json")
    _rewrite(document, tree, _bumped(SESSION_SCHEMA))


def _config_hash(tree: Tree) -> str:
    return str(read_manifest(tree.run)["identity"]["config_hash"])


def _summary_of(tree: Tree) -> dict[str, Any]:
    return _summary(tree.project)


RUN_LISTINGS: tuple[tuple[str, Callable[[Tree, str], Any], Any], ...] = (
    ("case_is_done", lambda t, h: case_is_done(t.project, RUN, h, "simulation"), False),
    ("effective_status", lambda t, h: effective_status(t.run), "unreadable"),
    ("case_state", lambda t, h: case_state(t.project, RUN).status, "planned"),
    ("running_cases", lambda t, h: running_cases(t.project, [RUN]), []),
    ("sealed_config_hash", lambda t, h: sealed_config_hash(t.run), None),
    ("project show", lambda t, h: _summary_of(t)["runs"].get("unreadable"), 1),
    (
        "gc plan",
        lambda t, h: (
            RUN_REL in plan_gc(t.project, RetentionPolicy(keep_versions=0), now=NOW).superseded_runs
        ),
        False,
    ),
)
"""What a run read by a later version answers, in each place a list or a decision reads it."""

RUN_REL = f"runs/{RUN}"


@pytest.mark.parametrize(
    ("name", "ask", "answer"), RUN_LISTINGS, ids=[name for name, _ask, _answer in RUN_LISTINGS]
)
def test_a_listing_with_one_unreadable_run_leaves_it_out(
    name: str,
    ask: Callable[[Tree, str], Any],
    answer: Any,
    tree: Tree,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_hash = _config_hash(tree)
    assert case_is_done(tree.project, RUN, config_hash, "simulation")
    _future_manifest(tree)

    with caplog.at_level(logging.WARNING):
        assert ask(tree, config_hash) == answer

    warned = [
        record
        for record in caplog.records
        if "is left out" in record.getMessage() and RUN in record.getMessage()
    ]
    assert warned or name == "running_cases"


def test_one_warning_names_an_unreadable_document(
    tree: Tree, caplog: pytest.LogCaptureFixture
) -> None:
    _future_manifest(tree)

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert readable(read_manifest, tree.run) is None

    warned = [record for record in caplog.records if "is left out" in record.getMessage()]
    assert len(warned) == 1
    assert str(tree.run) in warned[0].getMessage()
    assert "manifest_version" in warned[0].getMessage()


def test_a_missing_document_says_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert readable(read_manifest, tmp_path / "absent") is None
    assert caplog.records == []


def test_a_new_attempt_leaves_an_unreadable_run_as_it_is(tree: Tree) -> None:
    """A case with an unreadable run is not done, and running it takes a new version."""
    _future_manifest(tree)

    claim = claim_run_directory(tree.project, RUN, case_id=RUN, project="demo")

    assert claim.run_dir.name == f"{RUN}.v2"
    assert read_outcome(claim.run_dir) is not None


def test_an_unreadable_outcome_is_left_out_of_a_listing(tree: Tree) -> None:
    outcome = next(item for item in DOCUMENTS if item.name == "outcome.json")
    _rewrite(outcome, tree, _bumped(OUTCOME_SCHEMA))
    (tree.run / RUN_MANIFEST_FILENAME).unlink()

    assert effective_status(tree.run) == "unreadable"
    assert identity_of(tree.run) is None
    assert case_state(tree.project, RUN).status == "planned"


def test_annotations_that_do_not_read_keep_a_directory_protected(tree: Tree) -> None:
    annotations = next(item for item in DOCUMENTS if item.name == "annotations.json")
    _rewrite(annotations, tree, ANNOTATIONS_VERSION + 1)

    assert is_protected(tree.run)


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
"""What a session of a later version answers, wherever a list or a decision reads it."""


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
def test_a_listing_with_one_unreadable_session_leaves_it_out(
    name: str, ask: Callable[[Tree], Any], answer: Any, tree: Tree
) -> None:
    _future_session(tree)
    (tree.session / RUN_OUTCOME_FILENAME).unlink(missing_ok=True)

    assert ask(tree) == answer


def test_the_latest_session_is_the_latest_one_this_code_reads(tree: Tree) -> None:
    write_session_dir(tree.project, "older", started_at=NOW - timedelta(days=1))
    _future_session(tree)

    assert resolve_session_dir(tree.project, None).name == "older"
    assert [path.name for path, _ in readable_documents(read_session, [tree.session])] == []


def test_a_project_with_no_readable_session_says_so(tree: Tree) -> None:
    _future_session(tree)

    with pytest.raises(ConfigMissingError, match="No readable calibration session"):
        resolve_session_dir(tree.project, None)


def test_resume_of_an_unreadable_session_refuses_naming_its_version(tree: Tree) -> None:
    _future_session(tree)
    (tree.session / RUN_OUTCOME_FILENAME).unlink(missing_ok=True)
    directory, reopened = open_session_dir(tree.project, SESSION, resume=True)
    assert reopened and directory == tree.session

    with pytest.raises(SchemaVersionMismatchError, match=_bumped(SESSION_SCHEMA)):
        CalibrationPersistence(directory).resume_session()


def test_the_refusal_maps_to_the_schema_mismatch_exit_code() -> None:
    from hydromodpy.cli.helpers import EXIT_SCHEMA_MISMATCH, exit_code_for

    assert exit_code_for(SchemaVersionMismatchError("x")) == EXIT_SCHEMA_MISMATCH
