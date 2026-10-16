"""Every stored document carries its version, and every reader refuses another one.

The rule is :mod:`hydromodpy.core.io.document_version`: a document HydroModPy
writes on disk carries a ``schema`` id or an integer ``*_version``; its reader
refuses a document whose version it does not know, or that carries none, with
:class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`. The message
names the version read, the version this code reads and what to do. Stored
data is never migrated.

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

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_VERSION,
    read_lockfile_meta,
)
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.registry.freeze import write_lockfile
from hydromodpy.project.launch.lease import LEASE_SCHEMA, acquire_lease, lease_path, read_lease
from hydromodpy.results.annotations import ANNOTATIONS_VERSION, read_annotations
from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.catalog.index_schema import (
    INDEX_META_TABLE,
    INDEX_SCHEMA_VERSION,
    META_SCHEMA_VERSION,
)
from hydromodpy.results.heartbeat import HEARTBEAT_SCHEMA, heartbeat_path, read_heartbeat
from hydromodpy.results.identity import IDENTITY_SCHEMA, meta_sidecar_path, read_identity_from
from hydromodpy.results.ledger import LEDGER_SCHEMA, Ledger, LedgerEntry, ledger_path
from hydromodpy.results.manifest import RUN_RECORD_MANIFEST_VERSION, read_manifest
from hydromodpy.results.outcome import OUTCOME_SCHEMA, read_outcome
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
from hydromodpy.results.record import INPUTS_SCHEMA, RunRecord, read_inputs, read_provenance
from hydromodpy.results.session.descriptor import (
    SESSION_SCHEMA,
    read_session,
    session_descriptor_path,
)
from hydromodpy.results.session.journal import TRIAL_SCHEMA, read_trials, trials_path
from hydromodpy.results.session.phase import PHASE_SCHEMA, phase_dir, read_phase
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
from hydromodpy.results.storage.run_facts import (
    FACTS_SCHEMA,
    RunFacts,
    facts_path,
    read_facts,
    write_facts,
)
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

SEALED = f"Read it with the HydroModPy version that wrote it, hydromodpy_version = {WRITER}."
SEALED_SESSION = (
    f"Read it with the HydroModPy version that wrote it, hydromodpy_version = {VERSION}."
)
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
    write_session_dir(project, SESSION, phases=(PHASE,))
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
    acquire_lease(project)
    catalog = DataCatalogDuckDB(project / "data" / "cache.duckdb")
    lockfile = project / LOCKFILE_NAME
    write_lockfile(catalog, lockfile)
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
    remedy: str
    kind: str = "json"


DOCUMENTS: tuple[Document, ...] = (
    Document(
        "manifest.json",
        lambda t: t.run / RUN_MANIFEST_FILENAME,
        "manifest_version",
        RUN_RECORD_MANIFEST_VERSION,
        lambda t: read_manifest(t.run),
        SEALED,
    ),
    Document(
        "provenance.json",
        lambda t: t.run / RUN_PROVENANCE_FILENAME,
        "provenance_version",
        RUN_RECORD_MANIFEST_VERSION,
        lambda t: read_provenance(t.run),
        SEALED,
    ),
    Document(
        "inputs.json",
        lambda t: t.run / RUN_INPUTS_FILENAME,
        "schema",
        INPUTS_SCHEMA,
        lambda t: read_inputs(t.run),
        SEALED,
    ),
    Document(
        "outcome.json",
        lambda t: t.run / RUN_OUTCOME_FILENAME,
        "schema",
        OUTCOME_SCHEMA,
        lambda t: read_outcome(t.run),
        SEALED,
    ),
    Document(
        "annotations.json",
        lambda t: t.run / RUN_ANNOTATIONS_FILENAME,
        "annotations_version",
        ANNOTATIONS_VERSION,
        lambda t: read_annotations(t.run),
        SEALED,
    ),
    Document(
        "figures/index.json",
        lambda t: ledger_path(t.run / RUN_FIGURES_DIRNAME),
        "schema",
        LEDGER_SCHEMA,
        lambda t: Ledger.read(t.run / RUN_FIGURES_DIRNAME),
        SEALED,
    ),
    Document(
        "<file>.meta.json",
        lambda t: meta_sidecar_path(t.csv),
        "schema",
        IDENTITY_SCHEMA,
        lambda t: read_identity_from(t.csv),
        SEALED,
    ),
    Document(
        "published.jsonl",
        lambda t: published_path(t.run),
        "schema",
        PUBLISHED_SCHEMA,
        lambda t: read_published(t.run),
        SEALED,
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
        SEALED_SESSION,
    ),
    Document(
        "phases/<p>/session.json",
        lambda t: phase_dir(t.session, PHASE) / SESSION_DESCRIPTOR_FILENAME,
        "schema",
        PHASE_SCHEMA,
        lambda t: read_phase(t.session, PHASE),
        SEALED_SESSION,
    ),
    Document(
        "trials.jsonl",
        lambda t: trials_path(t.session),
        "schema",
        TRIAL_SCHEMA,
        lambda t: read_trials(t.session),
        SEALED_SESSION,
        kind="jsonl",
    ),
    Document(
        "plan/<hash>/plan.json",
        lambda t: t.project / "plan" / "0123abcd" / PLAN_FILENAME,
        "schema",
        PLAN_SCHEMA,
        lambda t: read_plan(t.project),
        SEALED,
    ),
    Document(
        "PUBLICATION.json",
        lambda t: publication_path(t.copy),
        "schema",
        PUBLICATION_SCHEMA,
        lambda t: read_publication(t.copy),
        SEALED,
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
        match = re.search(r'^version = "([^"]+)"', path.read_text(encoding="utf-8"), re.M)
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
        replacement = "" if version is None else f'version = "{version}"'
        path.write_text(
            re.sub(r'^version = "[^"]+"', replacement, text, count=1, flags=re.M),
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


@pytest.mark.parametrize("document", DOCUMENTS, ids=IDS)
def test_a_version_the_reader_does_not_know_is_refused_by_name(
    document: Document, tree: Tree
) -> None:
    bumped = _bumped(document.version)
    _rewrite(document, tree, bumped)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    message = str(refused.value)
    assert f"{document.key} = {bumped!r}" in message
    assert f"HydroModPy {HYDROMODPY_VERSION} reads {document.key} = {document.version!r}" in message
    assert document.remedy in message


@pytest.mark.parametrize("document", DOCUMENTS, ids=IDS)
def test_a_document_without_its_version_is_refused_by_name(document: Document, tree: Tree) -> None:
    _rewrite(document, tree, None)

    with pytest.raises(SchemaVersionMismatchError) as refused:
        document.read(tree)

    message = str(refused.value)
    assert f"carries no {document.key}" in message
    assert document.remedy in message


def test_the_refusal_maps_to_the_schema_mismatch_exit_code() -> None:
    from hydromodpy.cli.helpers import EXIT_SCHEMA_MISMATCH, exit_code_for

    assert exit_code_for(SchemaVersionMismatchError("x")) == EXIT_SCHEMA_MISMATCH
