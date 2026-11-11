"""What ``gc`` selects in a project tree, what it frees, and what a run weighs.

Every case builds the directories on disk, the way a run leaves them, and reads
the plan the module derives from them. No index is opened and nothing is
configured.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.state.layout import INTERNAL_DIRNAME
from hydromodpy.results import retention
from hydromodpy.results.annotations import Annotations, write_annotations
from hydromodpy.results.products.cited import CitedProduct, write_cited
from hydromodpy.results.products.store import META_FILENAME, ProductStore, products_root
from hydromodpy.results.retention import (
    DEAD_SCRATCH_AGE,
    RetentionPolicy,
    apply_gc,
    level_at,
    plan_gc,
    project_weight,
    run_weight,
)
from hydromodpy.results.session.descriptor import write_session
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    MESH_DIRNAME,
    PUBLICATION_FILENAME,
    RUN_ATTEMPTS_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    RUN_PURGED_FILENAME,
)
from hydromodpy.results.storage.kept import Purged, read_purged, write_purged
from hydromodpy.results.trash import list_trash
from tests._helpers.sealed_runs import (
    NOW,
    make_project,
    manifest_document,
    seal_run,
    write_attempt,
)
from tests._helpers.session_documents import best_trial, session_descriptor

QUIET = {"keep_versions": None, "trial_fields_days": None}


def _dead_pid() -> int:
    """A pid that belonged to a process of this host and is gone."""
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


def _write(path: Path, size: int) -> Path:
    """Write a file of *size* bytes, with its folders, and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _seal(directory: Path, *, sealed_at: datetime, kind: str | None = None) -> None:
    """Write the manifest of a sealed directory, its lineage *kind* when given."""
    directory.mkdir(parents=True, exist_ok=True)
    lineage = None if kind is None else {"kind": kind, "trial": 1, "session_id": "s" * 32}
    document = manifest_document(
        name=directory.name,
        sealed_at=sealed_at.isoformat(),
        lineage=lineage or {},
    )
    (directory / RUN_MANIFEST_FILENAME).write_text(json.dumps(document), encoding="utf-8")


def _policy(**fields: object) -> RetentionPolicy:
    return RetentionPolicy(**{**QUIET, **fields})


def _age(tree: Path, age: timedelta) -> None:
    """Date back every file and folder of *tree* by *age*."""
    stamp = (datetime.now(UTC) - age).timestamp()
    for path in (*tree.rglob("*"), tree):
        os.utime(path, (stamp, stamp))


@pytest.fixture
def arrived_long_ago(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every trial directory reach the project a year before ``NOW``.

    No call can set the inode change a directory carries, so the tests that
    date a trial by its seal date its arrival this way.
    """
    monkeypatch.setattr(retention, "_arrival", lambda directory: NOW - timedelta(days=365))


# --- Scratch of a dead writer -------------------------------------------------


def test_a_dead_scratch_folder_leaves_a_live_one_and_a_fresh_one_stay(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    scratch = project / INTERNAL_DIRNAME / "scratch"
    dead_pid = _dead_pid()
    _write(scratch / f"deadrun.p{dead_pid}" / "work.npz", 11)
    live = _write(scratch / f"liverun.p{os.getpid()}" / "work.npz", 22)
    old = _write(scratch / f"oldrun.p{os.getpid()}" / "deep" / "work.npz", 44)
    _age(old.parent.parent, DEAD_SCRATCH_AGE + timedelta(hours=1))
    written = _write(scratch / f"written.p{os.getpid()}" / "deep" / "work.npz", 55)
    _age(written.parent.parent, DEAD_SCRATCH_AGE + timedelta(hours=1))
    written.touch()

    plan = plan_gc(project, _policy(), now=datetime.now(UTC))

    assert plan.dead_scratch == (
        f"{INTERNAL_DIRNAME}/scratch/deadrun.p{dead_pid}",
        f"{INTERNAL_DIRNAME}/scratch/oldrun.p{os.getpid()}",
    )
    assert plan.bytes_of("dead_scratch") == 11 + 44
    assert live.parent.is_dir() and written.is_file()


def test_a_resumed_scratch_its_holder_keeps_alive_stays(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    scratch = project / INTERNAL_DIRNAME / "scratch"
    key = f"resumed.p{_dead_pid()}"
    _write(scratch / key / "work.npz", 11)
    (scratch / f"{key}.holder").write_text(str(os.getpid()), encoding="ascii")

    plan = plan_gc(project, _policy(), now=datetime.now(UTC))

    assert plan.dead_scratch == ()


def test_a_folder_of_the_scratch_that_names_no_run_stays_whatever_its_age(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path / "p")
    scratch = project / INTERNAL_DIRNAME / "scratch"
    kept = _write(scratch / "_preprocessing" / "geographic" / "dem.tif", 33)
    _age(scratch / "_preprocessing", DEAD_SCRATCH_AGE * 10)

    plan = plan_gc(project, _policy(), now=datetime.now(UTC))

    assert plan.dead_scratch == ()
    assert kept.is_file()


def test_the_scratch_of_a_run_a_live_session_carries_stays(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    scratch = project / INTERNAL_DIRNAME / "scratch"
    _write(scratch / f"calib.p{_dead_pid()}" / "work.npz", 11)
    write_attempt(
        project,
        "sessions/calib",
        status="running",
        host=socket.gethostname(),
        pid=os.getpid(),
        heartbeat_age_s=5,
    )

    plan = plan_gc(project, _policy(), now=datetime.now(UTC))

    assert plan.dead_scratch == ()


# --- Attempts of a sealed run -------------------------------------------------


def test_attempts_leave_only_from_a_sealed_run_and_their_outcomes_stay(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    sealed = seal_run(project, "sealed")
    attempt = project / "runs" / "sealed" / RUN_ATTEMPTS_DIRNAME / "1"
    _write(attempt / RUN_OUTCOME_FILENAME, 12)
    _write(attempt / "logs" / "run.log", 20)
    _write(attempt / "stop.json", 3)
    write_attempt(project, "runs/failed", status="failed", error=("SolverError", "stopped"))
    _write(project / "runs" / "failed" / RUN_ATTEMPTS_DIRNAME / "1" / "logs" / "run.log", 13)

    plan = plan_gc(project, _policy(), now=datetime.now(UTC))
    apply_gc(plan, now=datetime.now(UTC))

    rel = f"runs/sealed/{RUN_ATTEMPTS_DIRNAME}/1"
    assert plan.sealed_attempts == (f"{rel}/logs", f"{rel}/stop.json")
    assert plan.bytes_of("sealed_attempts") == 20 + 3
    assert [path.name for path in attempt.iterdir()] == [RUN_OUTCOME_FILENAME]
    assert sealed


# --- Fields of a kept trial ---------------------------------------------------


def _trial_session(
    project: Path, name: str, *, best: int | None, status: str = "completed"
) -> Path:
    session = project / "sessions" / name
    write_session(
        session,
        session_descriptor(
            name,
            site="demo",
            best=None if best is None else best_trial(best),
            status=status,
        ),
    )
    return session


def test_the_fields_of_a_kept_trial_leave_after_ninety_days_all_but_the_best(
    tmp_path: Path, arrived_long_ago: None
) -> None:
    project = make_project(tmp_path / "p")
    session = _trial_session(project, "calib", best=1)
    trials = session / "trials"

    _seal(trials / "0001", sealed_at=NOW - timedelta(days=200), kind="trial")
    _write(trials / "0001" / FIELDS_STORE_NAME / "chunk", 1)

    _seal(trials / "0002", sealed_at=NOW - timedelta(days=91), kind="trial")
    _write(trials / "0002" / FIELDS_STORE_NAME / "chunk", 10)
    _write(trials / "0002" / MESH_DIRNAME / "grid.npz", 5)

    _seal(trials / "0003", sealed_at=NOW - timedelta(days=89), kind="trial")
    _write(trials / "0003" / FIELDS_STORE_NAME / "chunk", 10)

    _seal(trials / "0004", sealed_at=NOW - timedelta(days=100), kind="trial")
    _write(trials / "0004" / FIELDS_STORE_NAME / "chunk", 10)
    write_annotations(trials / "0004", Annotations(sim_id="t4", tags=("pinned",)))

    _seal(trials / "0005", sealed_at=NOW - timedelta(days=100), kind="trial")
    _write(trials / "0005" / FIELDS_STORE_NAME / "chunk", 10)
    write_purged(
        trials / "0005", Purged(at=NOW - timedelta(days=1), entries={FIELDS_STORE_NAME: 1})
    )

    _seal(trials / "0006" / "caseA", sealed_at=NOW - timedelta(days=100), kind="trial")
    _write(trials / "0006" / "caseA" / MESH_DIRNAME / "grid.npz", 7)

    live = _trial_session(project, "live", best=None, status="running")
    _seal(live / "trials" / "0007", sealed_at=NOW - timedelta(days=100), kind="trial")
    _write(live / "trials" / "0007" / FIELDS_STORE_NAME / "chunk", 10)

    nobest = _trial_session(project, "nobest", best=None)
    _seal(nobest / "trials" / "0001", sealed_at=NOW - timedelta(days=100), kind="trial")
    _write(nobest / "trials" / "0001" / FIELDS_STORE_NAME / "chunk", 10)

    plan = plan_gc(project, _policy(trial_fields_days=90), now=NOW)

    # 0002 is old, 0005 is a purge cut short that its witness names; the mesh
    # of 0002 and of 0006 stays, since a replay reads it.
    assert plan.old_trial_fields == (
        "sessions/calib/trials/0002",
        "sessions/calib/trials/0005",
    )
    assert plan.bytes_of("old_trial_fields") == 10 + 10


def test_the_trials_of_an_imported_session_count_from_their_arrival(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    session = _trial_session(project, "calib", best=1)
    _seal(session / "trials" / "0002", sealed_at=NOW - timedelta(days=400), kind="trial")
    _write(session / "trials" / "0002" / FIELDS_STORE_NAME / "chunk", 10)
    _age(session, timedelta(days=400))

    plan = plan_gc(project, _policy(trial_fields_days=90), now=datetime.now(UTC))

    assert plan.old_trial_fields == ()


def test_trial_fields_stay_when_the_policy_turns_the_rule_off(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    session = _trial_session(project, "calib", best=1)
    _seal(session / "trials" / "0002", sealed_at=NOW - timedelta(days=400), kind="trial")
    _write(session / "trials" / "0002" / FIELDS_STORE_NAME / "chunk", 10)

    plan = plan_gc(project, _policy(trial_fields_days=None), now=NOW)

    assert plan.old_trial_fields == ()


def test_a_purge_witness_of_another_schema_is_refused(tmp_path: Path) -> None:
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / RUN_PURGED_FILENAME).write_text(
        json.dumps({"schema": "hydromodpy.purged.v2", "at": NOW.isoformat(), "entries": {}}),
        encoding="utf-8",
    )

    with pytest.raises(SchemaVersionMismatchError, match="hydromodpy.purged.v1"):
        read_purged(trial)


# --- Product store over its cap ----------------------------------------------


def _product(project: Path, seed: bytes, *, size: int, written_at: float) -> str:
    """Store one product of *size* bytes, stamped *written_at*, and return its key."""
    key = hashlib.sha256(seed).hexdigest()
    store = ProductStore(products_root(project))
    store.put(key, "mesh", lambda folder: (folder / "blob").write_bytes(b"x" * size))
    meta = store.path(key) / META_FILENAME
    payload = json.loads(meta.read_text(encoding="utf-8"))
    payload["bytes"] = size
    payload["written_at"] = written_at
    meta.write_text(json.dumps(payload), encoding="utf-8")
    return key


def test_gc_removes_the_products_its_dry_run_lists_and_no_other(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    keys = [
        _product(project, bytes([index]), size=100, written_at=float(index)) for index in range(6)
    ]

    plan = plan_gc(project, _policy(), now=NOW, products_cap_bytes=450)
    freed = apply_gc(plan, now=NOW)

    listed = tuple(f"{INTERNAL_DIRNAME}/products/{key[:2]}/{key}" for key in keys[:2])
    assert plan.products == listed
    assert freed["products"] == plan.bytes_of("products") == 200
    store = ProductStore(products_root(project))
    assert sorted(entry.key for entry in store.entries()) == sorted(keys[2:])


def test_products_go_down_to_the_cap_and_a_key_a_live_run_cites_stays(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path / "p")
    cited = _product(project, b"cited", size=100, written_at=1.0)
    spare = _product(project, b"spare", size=100, written_at=2.0)
    live = "runs/live"
    write_attempt(
        project,
        live,
        status="running",
        host=socket.gethostname(),
        pid=os.getpid(),
        heartbeat_age_s=5,
    )
    write_cited(project / live, [CitedProduct(kind="mesh", key=cited)])

    plan = plan_gc(project, _policy(), now=datetime.now(UTC), products_cap_bytes=150)

    assert plan.products == (f"{INTERNAL_DIRNAME}/products/{spare[:2]}/{spare}",)
    assert plan.bytes_of("products") == 100


# --- Weight of a run and of a project ----------------------------------------


def test_run_weight_sums_the_bytes_of_every_family(tmp_path: Path) -> None:
    run = tmp_path / "project" / "runs" / "a"
    _write(run / FIELDS_STORE_NAME / "head", 10)
    _write(run / FIELDS_STORE_NAME / "budget" / "term", 20)
    _write(run / FIELDS_STORE_NAME / "face_flow" / "flow", 30)
    _write(run / FIELDS_STORE_NAME / "connection_cells" / "pairs", 40)
    _write(run / MESH_DIRNAME / "grid.npz", 50)
    _write(run / "final_state" / "state", 60)
    _write(run / "tables.parquet" / "table", 70)
    _write(run / "figures" / "map.png", 80)
    _write(run / "exports" / "values.csv", 90)
    _write(run / "report" / "report.html", 100)
    _write(run / "solver" / "flow.cbc", 110)
    _write(run / RUN_ATTEMPTS_DIRNAME / "a1" / "outcome.json", 120)
    _write(run / "logs" / "run.log", 130)
    _write(run / INTERNAL_DIRNAME / "journal.json", 140)
    _write(run / RUN_MANIFEST_FILENAME, 1)
    _write(run / "config.toml", 2)

    weight = run_weight(run)

    assert weight == {
        "fields": 10 + 50 + 60,
        "budget": 20,
        "face_flow": 30 + 40,
        "tables": 70,
        "documents": 1 + 2,
        "renders": 80 + 90 + 100,
        "solver_files": 110,
        "history": 120 + 130 + 140,
        "other": 0,
    }
    assert sum(weight.values()) == sum(
        path.stat().st_size for path in run.rglob("*") if path.is_file()
    )


def test_project_weight_sums_the_bytes_of_every_family(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    first = project / "runs" / "a"
    _write(first / FIELDS_STORE_NAME / "head", 10)
    _write(first / "tables.parquet" / "t", 20)
    second = project / "runs" / "b"
    _write(second / "manifest.json", 500)
    session = project / "sessions" / "calib"
    _write(session / "session.json", 5)
    _write(session / "trials" / "0001" / "manifest.json", 6)
    _write(session / "trial_series" / "0001.parquet", 7)
    _write(project / INTERNAL_DIRNAME / "products" / "ab" / "k" / "meta.json", 8)
    _write(project / INTERNAL_DIRNAME / "index.duckdb", 9)
    _write(project / INTERNAL_DIRNAME / "scratch" / "r.p1" / "work", 11)
    _write(project / INTERNAL_DIRNAME / "logs" / "hmp.log", 12)
    _write(project / INTERNAL_DIRNAME / "mesh_cache" / "m", 13)
    _write(project / "trash" / "runs" / "gone" / "tombstone.json", 14)
    _write(project / "inputs" / "request.json", 15)
    _write(project / "data" / "variable" / "file.csv", 16)
    _write(project / "project.toml", 17)

    weight = project_weight(project)

    assert weight["runs"] == sum(run_weight(first).values()) + 500
    assert weight["trials"] == 6
    assert weight["series"] == 7
    assert weight["sessions_other"] == 5
    assert weight["products"] == 8
    assert weight["index"] == 9
    assert weight["scratch"] == 11
    assert weight["logs"] == 12
    assert weight["trash"] == 14
    assert weight["inputs"] == 15
    assert weight["data"] == 16
    assert weight["other"] == 13 + 17
    assert weight.total() == sum(
        path.stat().st_size for path in project.rglob("*") if path.is_file()
    )


# --- The plan says what applying it frees ------------------------------------


def test_applying_the_plan_frees_the_bytes_the_plan_announces(
    tmp_path: Path, arrived_long_ago: None
) -> None:
    project = make_project(tmp_path / "p")
    for name, size in (("x.v3", 30), ("x.v2", 20), ("x", 10)):
        _write(project / "runs" / name / "tables.parquet" / "part.parquet", size)
    _write(project / INTERNAL_DIRNAME / "scratch" / f"dead.p{_dead_pid()}" / "work", 40)
    seal_run(project, "sealed")
    _write(project / "runs" / "sealed" / RUN_ATTEMPTS_DIRNAME / "1" / "logs" / "run.log", 50)
    session = _trial_session(project, "calib", best=1)
    _seal(session / "trials" / "0002", sealed_at=NOW - timedelta(days=100), kind="trial")
    _write(session / "trials" / "0002" / FIELDS_STORE_NAME / "chunk", 60)
    _write(session / "trials" / "0002" / MESH_DIRNAME / "grid.npz", 6)
    policy = _policy(keep_versions=1, trial_fields_days=90)

    plan = plan_gc(project, policy, now=NOW)
    freed = apply_gc(plan, now=NOW)

    assert plan.superseded_runs == ("runs/x", "runs/x.v2")
    for category in (
        "superseded_runs",
        "dead_scratch",
        "sealed_attempts",
        "old_trial_fields",
    ):
        assert freed[category] == plan.bytes_of(category), category
    assert freed["superseded_runs"] == 10 + 20
    assert freed["dead_scratch"] == 40
    assert freed["sealed_attempts"] == 50
    assert freed["old_trial_fields"] == 60
    assert sorted(entry.rel_dir for entry in list_trash(project)) == ["runs/x", "runs/x.v2"]
    assert not (project / plan.dead_scratch[0]).exists()
    assert not (project / "runs" / "sealed" / RUN_ATTEMPTS_DIRNAME / "1" / "logs").exists()
    trial = session / "trials" / "0002"
    assert not (trial / FIELDS_STORE_NAME).exists() and (trial / MESH_DIRNAME).is_dir()
    purged = read_purged(trial)
    assert purged is not None and purged.entries == {FIELDS_STORE_NAME: 60}


def test_a_purge_that_fails_keeps_its_witness_and_the_next_gc_takes_it_up(
    tmp_path: Path, arrived_long_ago: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path / "p")
    session = _trial_session(project, "calib", best=1)
    trial = session / "trials" / "0002"
    _seal(trial, sealed_at=NOW - timedelta(days=100), kind="trial")
    _write(trial / FIELDS_STORE_NAME / "chunk", 60)
    policy = _policy(trial_fields_days=90)

    def refuse(path, *args, **kwargs):
        raise PermissionError(f"{path} is busy")

    with monkeypatch.context() as patched:
        patched.setattr(retention.shutil, "rmtree", refuse)
        freed = apply_gc(plan_gc(project, policy, now=NOW), now=NOW)

    assert freed["old_trial_fields"] == 0
    assert (trial / FIELDS_STORE_NAME / "chunk").is_file()
    witness = read_purged(trial)
    assert witness is not None and witness.entries == {FIELDS_STORE_NAME: 60}

    again = plan_gc(project, policy, now=NOW + timedelta(days=1))
    assert again.old_trial_fields == ("sessions/calib/trials/0002",)
    assert apply_gc(again, now=NOW + timedelta(days=1))["old_trial_fields"] == 60
    assert not (trial / FIELDS_STORE_NAME).exists()
    assert read_purged(trial) == witness


def test_the_trash_it_removes_is_measured_before_it_leaves(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    _write(project / "runs" / "gone" / "tables.parquet" / "part", 70)
    old = NOW - timedelta(days=60)
    retention.trash_run(project, "runs/gone", now=old)

    plan = plan_gc(project, _policy(), now=NOW)
    freed = apply_gc(plan, now=NOW)

    assert len(plan.expired_trash) == 1
    assert freed["expired_trash"] == plan.bytes_of("expired_trash") > 0


# --- The level of a run directory --------------------------------------------


@pytest.mark.parametrize(
    ("kind", "published", "expected"),
    [
        (None, False, "result"),
        ("trial", False, "research"),
        ("promoted", False, "result"),
        ("rerun", False, "result"),
        ("version", False, "result"),
        ("replay", False, "result"),
        (None, True, "publication"),
        ("trial", True, "publication"),
    ],
)
def test_level_at_reads_the_seal_and_the_published_copy(
    tmp_path: Path, kind: str | None, published: bool, expected: str
) -> None:
    run = tmp_path / "run"
    _seal(run, sealed_at=NOW, kind=kind)
    if published:
        (run / PUBLICATION_FILENAME).write_text("{}", encoding="utf-8")

    assert level_at(run) == expected


def test_level_at_refuses_a_run_whose_seal_does_not_read(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / RUN_MANIFEST_FILENAME).write_text("{", encoding="utf-8")

    with pytest.raises(ValueError):
        level_at(run)
