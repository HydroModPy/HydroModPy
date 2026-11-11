"""A seal, a replay, a publication and an attempt refuse what would say two things at once.

Each table is a family of refusals. A row gives the document or the directory that is
wrong, the class that refuses it and a fragment of the sentence that says what to do.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import zarr
from pydantic import ValidationError

from hydromodpy.core.exceptions import (
    ConfigValidationError,
    ExportError,
    JobUsageError,
    SchemaVersionMismatchError,
)
from hydromodpy.core.io.document_version import NEWER_REMEDY, OLDER_REMEDY
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.results.export.publish import publish
from hydromodpy.results.record.replay_class import ReplayDeviationError, classify_replay
from hydromodpy.results.record.values import stored_value_digests
from hydromodpy.results.storage.attempt import (
    AttemptClaimedError,
    CaseAliveError,
    DirectoryWithoutOutcomeError,
    claim_run_directory,
)
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.outcome import (
    JobOutcome,
    OutputRecord,
    dismissed,
    error_record,
    now,
)
from hydromodpy.schema.job.reuse import REUSED_MEMBER, reuse_sealed_outcome, reused_outcome_text
from hydromodpy.schema.job.seal import JobSeal, read_job_seal
from hydromodpy.schema.seal import (
    ArtifactRecord,
    Seal,
    ValueDigests,
    render_document,
    verify_artifacts,
    write_seal,
)
from tests._helpers.published_runs import RUN_NAME, make_project, make_sealed_run
from tests._helpers.run_stores import claim_run

SEALED_AT = datetime(2026, 1, 1, tzinfo=UTC)

# --- the seal of a job, read from a file ---------------------------------------------------

JOB_SEAL_FILES = [
    pytest.param(
        json.dumps({"manifest_version": 4, "sealed_at": "2026-01-01T00:00:00+00:00"}),
        "profile",
        id="no profile",
    ),
    pytest.param(
        json.dumps(
            {"manifest_version": 4, "profile": "run", "sealed_at": "2026-01-01T00:00:00+00:00"}
        ),
        "run",
        id="the profile of a run",
    ),
    pytest.param(
        json.dumps({"manifest_version": 5, "profile": "job"}),
        f"manifest_version = 5.*{NEWER_REMEDY}",
        id="a newer version",
    ),
    pytest.param(
        json.dumps({"manifest_version": 3, "profile": "job"}),
        f"manifest_version = 3.*{OLDER_REMEDY}",
        id="an older version",
    ),
    pytest.param(json.dumps({"schema": "hmp-manifest/v9"}), "hmp-manifest/v9", id="another schema"),
    pytest.param("[]", "not a JSON object", id="an array"),
]


@pytest.mark.parametrize(("text", "said"), JOB_SEAL_FILES)
def test_a_job_seal_that_cannot_be_read_is_refused_by_the_version(
    tmp_path: Path, text: str, said: str
) -> None:
    target = tmp_path / "manifest.json"
    target.write_text(text, encoding="utf-8")

    with pytest.raises(SchemaVersionMismatchError, match=said):
        read_job_seal(target)


@pytest.mark.parametrize(
    ("payload", "said"),
    [
        pytest.param({"sealed_at": "2026-01-01T00:00:00+00:00"}, "profile", id="no profile"),
        pytest.param({"profile": "run"}, "sealed_at", id="no instant"),
    ],
)
def test_a_seal_without_its_two_members_is_refused(payload: dict[str, Any], said: str) -> None:
    with pytest.raises(ValidationError, match=said):
        Seal.model_validate(payload)


def test_a_seal_is_strict_json() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        render_document({"max_abs": float("inf")})


# --- the artifacts a seal lists --------------------------------------------------------------


def _record(path: str, **fields: Any) -> Seal:
    record = ArtifactRecord(path=path, role="document", **fields)
    return Seal(profile="job", sealed_at=SEALED_AT, artifacts=[record])


def test_a_sealed_file_that_is_absent_is_named(tmp_path: Path) -> None:
    assert verify_artifacts(tmp_path, _record("outcome.json")) == (
        "outcome.json is sealed and absent",
    )


def test_a_sealed_file_that_changed_gives_its_size_and_its_digest(tmp_path: Path) -> None:
    path = tmp_path / "outcome.json"
    path.write_text("{}\n", encoding="utf-8")
    digest, size = sha256_and_size(path)
    path.write_text('{"a": 1}\n', encoding="utf-8")

    problems = verify_artifacts(tmp_path, _record("outcome.json", bytes=size, sha256=digest))

    assert len(problems) == 2
    assert all(problem.startswith("outcome.json") for problem in problems)


def test_a_sealed_entry_outside_the_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path.parent / "elsewhere.json").write_text("{}\n", encoding="utf-8")

    assert verify_artifacts(tmp_path / "job", _record("../elsewhere.json")) == (
        "../elsewhere.json is sealed and lies outside " + str(tmp_path / "job"),
    )


def test_a_directory_is_read_by_the_tree_digest_the_caller_gives(tmp_path: Path) -> None:
    (tmp_path / "fields.zarr").mkdir()
    seal = _record("fields.zarr", sha256="abc")

    assert verify_artifacts(tmp_path, seal, tree_digest=lambda path: "abc") == ()
    assert verify_artifacts(tmp_path, seal, tree_digest=lambda path: "def") == (
        "fields.zarr does not hash to what the seal recorded",
    )


# --- a sealed job that is reused, not rerun ----------------------------------------------------

JOB_ID = "sha256:" + "7" * 64
OTHER_JOB_ID = "sha256:" + "8" * 64


def _outcome(**overrides: object) -> JobOutcome:
    started = now()
    payload: dict[str, object] = {
        "job_id": JOB_ID,
        "process_id": "demo-delineate",
        "process_version": "1.2.3",
        "status": "successful",
        "exit_code": 0,
        "started_at": started,
        "finished_at": now(),
        "outputs": (
            OutputRecord(
                id="watershed_vector",
                path="outputs/watershed.gpkg",
                media_type="application/geopackage+sqlite3",
                bytes=17,
                sha256="a" * 64,
            ),
        ),
    }
    payload.update(overrides)
    return JobOutcome(**payload)  # type: ignore[arg-type]


@pytest.fixture
def sealed(tmp_path: Path) -> JobDirectory:
    """A directory that holds a finished job, sealed under ``JOB_ID``."""
    job = JobDirectory.create(tmp_path / "job")
    job.request_path.write_text("{}", encoding="utf-8")
    _outcome().write(job)
    write_seal(job.manifest_path, JobSeal(sealed_at=now(), request_id=JOB_ID))
    return job


def _write_manifest(text: str) -> Callable[[JobDirectory], None]:
    return lambda job: job.manifest_path.write_text(text, encoding="utf-8")


def _edit_outcome(**changes: object) -> Callable[[JobDirectory], None]:
    def edit(job: JobDirectory) -> None:
        document = read_document(job.outcome_path)
        for key, value in changes.items():
            if value is None:
                document.pop(key, None)
            else:
                document[key] = value
        write_document(job.outcome_path, document)

    return edit


def _later_manifest(job: JobDirectory) -> None:
    write_document(job.manifest_path, {"manifest_version": 5, "profile": "job"})


UNREADABLE_JOBS = [
    pytest.param(
        _write_manifest("{oh dear"),
        SchemaVersionMismatchError,
        "does not read as JSON",
        id="a seal that is not JSON",
    ),
    pytest.param(
        _later_manifest,
        SchemaVersionMismatchError,
        "manifest_version = 4",
        id="a seal of a later version",
    ),
    pytest.param(
        _edit_outcome(schema="hmp-outcome/v2"),
        SchemaVersionMismatchError,
        NEWER_REMEDY,
        id="an outcome of a later version",
    ),
    pytest.param(
        _write_manifest("[]"),
        SchemaVersionMismatchError,
        "not a JSON object",
        id="a seal that is not an object",
    ),
    pytest.param(
        _edit_outcome(status=None),
        JobUsageError,
        "cannot be read as an outcome",
        id="an outcome nobody can parse",
    ),
    pytest.param(
        _edit_outcome(**{REUSED_MEMBER: None}),
        JobUsageError,
        "cannot be read as an outcome",
        id="an outcome without the reuse member",
    ),
    pytest.param(
        _edit_outcome(status="accepted", exit_code=130),
        JobUsageError,
        "cannot be read as an outcome",
        id="a status no capability writes",
    ),
]


@pytest.mark.parametrize(("damage", "error", "said"), UNREADABLE_JOBS)
def test_a_sealed_directory_nobody_can_read_is_refused_not_a_crash(
    sealed: JobDirectory, damage: Callable[[JobDirectory], None], error: type[Exception], said: str
) -> None:
    damage(sealed)

    with pytest.raises(error, match=said):
        reuse_sealed_outcome(sealed, job_id=JOB_ID)


def test_an_outcome_without_the_reuse_member_is_refused_at_the_text_too(
    sealed: JobDirectory,
) -> None:
    _edit_outcome(**{REUSED_MEMBER: None})(sealed)

    with pytest.raises(JobUsageError, match="carries no 'reused' member"):
        reused_outcome_text(sealed)


def test_another_id_is_refused_and_nothing_is_written(sealed: JobDirectory) -> None:
    before = {path.name: path.read_bytes() for path in sealed.root.iterdir() if path.is_file()}

    with pytest.raises(JobUsageError) as caught:
        reuse_sealed_outcome(sealed, job_id=OTHER_JOB_ID)

    assert JOB_ID in str(caught.value) and OTHER_JOB_ID in str(caught.value)
    assert before == {
        path.name: path.read_bytes() for path in sealed.root.iterdir() if path.is_file()
    }


# --- an outcome that cannot contradict itself --------------------------------------------------

STARTED = "2026-09-16T08:12:05.113000+00:00"
FINISHED = "2026-09-16T08:14:41.882000+00:00"
FAILURE = error_record(ConfigValidationError("the request failed validation"))

CONTRADICTIONS = [
    pytest.param({"exit_code": 14}, "succeeded and exits", id="a success that exits non-zero"),
    pytest.param({"errors": (FAILURE,)}, "succeeded and carries", id="a success with an error"),
    pytest.param(
        {"status": "failed", "exit_code": 0, "outputs": (), "errors": (FAILURE,)},
        "failed and exits 0",
        id="a failure that exits zero",
    ),
    pytest.param(
        {"status": "failed", "exit_code": 14, "outputs": ()},
        "says why nowhere",
        id="a failure that says nothing",
    ),
    pytest.param(
        {"status": "dismissed", "exit_code": 1, "outputs": (), "errors": (FAILURE,)},
        "dismissed and exits",
        id="a dismissal under another code",
    ),
    pytest.param(
        {"started_at": FINISHED, "finished_at": STARTED},
        "before it started",
        id="finished before it started",
    ),
    pytest.param(
        {"started_at": "2026-09-16T08:12:05.113000"},
        "without a UTC offset",
        id="an instant without an offset",
    ),
    pytest.param({"started_at": "the day before yesterday"}, "not an instant", id="not an instant"),
]


@pytest.mark.parametrize(("changes", "said"), CONTRADICTIONS)
def test_an_outcome_that_says_two_things_is_refused(changes: dict[str, Any], said: str) -> None:
    fields: dict[str, Any] = {"started_at": STARTED, "finished_at": FINISHED}

    with pytest.raises(ValueError, match=said):
        _outcome(**{**fields, **changes})


def test_a_cancellation_from_a_local_clock_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="started_at"):
        dismissed(
            job_id=JOB_ID,
            process_id="demo-delineate",
            process_version="1.2.3",
            started_at="2026-09-16T08:12:05.113000",
            exc=KeyboardInterrupt(),
        )


# --- a replay is published only when it is classed bit --------------------------------------------

SOURCE_SIM_ID = "9a4f0000-0000-4000-8000-000000000001"
DEVIATION_REFUSAL = (
    f"runs/{RUN_NAME} replays runs/source and its values differ from the seal (class "
    "deviation: fields/head). A published copy states that it gives the sealed numbers, so it "
    "is not published. Publish runs/source itself, or a replay classed bit."
)
CLASSLESS_REFUSAL = (
    f"runs/{RUN_NAME} replays a copy that carried no values, so it was never compared with "
    "the seal. A published copy states that it gives the sealed numbers: replay a copy that "
    "carries its results, or publish the source run itself."
)


def _make_replay(run_dir: Path, *, basis: str, class_: str | None) -> None:
    """Rewrite the lineage of the seal of *run_dir* as a replay of the run ``runs/source``."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    replay: dict[str, Any] = {
        "of": SOURCE_SIM_ID,
        "source": "copy" if basis == "none" else "run",
        "source_version": "2.1.0",
        "basis": basis,
    }
    if class_ is not None:
        replay["class"] = class_
    if class_ == "deviation":
        replay["differs"] = {"fields/head": {"max_abs": 1e-4, "rel_l2": 2e-6, "precision": "exact"}}
    manifest["lineage"] = {**manifest["lineage"], "kind": "replay", "replay": replay}
    manifest["run"]["sim_id"] = "1b2c0000-0000-4000-8000-000000000002"
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    ("basis", "class_", "refusal"),
    [
        pytest.param("float64", "deviation", DEVIATION_REFUSAL, id="deviation"),
        pytest.param("none", None, CLASSLESS_REFUSAL, id="classless"),
    ],
)
def test_a_replay_not_classed_bit_is_not_published(
    tmp_path: Path, basis: str, class_: str | None, refusal: str
) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    shutil.copytree(run_dir, project / "runs" / "source")
    _make_replay(run_dir, basis=basis, class_=class_)
    target = tmp_path / "out" / "copy"

    with pytest.raises(ExportError) as refused:
        publish(run_dir, target, project_root=project, with_=("results",))

    assert refused.value.code == "HMPY.E506"
    assert str(refused.value) == refusal
    assert not target.exists()


# --- a strict replay refuses a deviation ------------------------------------------------------------

HEADS = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)


def _seal_payload(values: ValueDigests | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "manifest_version": 4,
        "profile": "run",
        "sealed_at": "2026-01-01T00:00:00+00:00",
        "run": {
            "sim_id": "source-run",
            "name": "island",
            "name_stem": "island",
            "version": 1,
            "status": "completed",
            "project": "island",
            "case_id": "island",
            "rel_dir": "runs/island",
            "attempt": 1,
            "attempt_id": "att",
            "solver": "modflow6",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        "geometry": {"mesh_engine": "regular"},
        "period": {},
        "config": {"file": "config.toml"},
        "identity": {
            "case_id": "island",
            "sim_id": "source-run",
            "attempt_id": "att",
            "hydromodpy_version": "2.0.0",
        },
        "checks": {},
        "artifacts": [],
    }
    if values is not None:
        payload["values"] = values.model_dump(mode="json")
    return payload


def _run_with(root: Path, payload: dict[str, Any], heads: np.ndarray) -> Path:
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    group = zarr.open_group(str(root / "fields.zarr"), mode="w")
    group.attrs["zarr_schema_version"] = ZARR_SCHEMA_VERSION
    array = group.create_array("heads", shape=heads.shape, dtype="float64")
    array[:] = heads
    return root


def test_a_strict_replay_refuses_a_deviation(tmp_path: Path) -> None:
    moved = HEADS.copy()
    moved[0, 0] = 1.5
    source = _run_with(tmp_path / "source", _seal_payload(), HEADS)
    replay = _run_with(tmp_path / "replay", _seal_payload(), moved)
    sealed_values = _seal_payload(stored_value_digests(source))
    (source / "manifest.json").write_text(json.dumps(sealed_values), encoding="utf-8")

    with pytest.raises(ReplayDeviationError, match="fields/heads") as raised:
        classify_replay(source, replay, stored_value_digests(replay), strict=True)

    assert raised.value.code == "HMPY.E900"
    assert "without --strict" in raised.value.message


# --- a case that cannot be claimed -------------------------------------------------------------------


def _claim(project: Path, *, when: datetime | None = None) -> Any:
    return claim_run_directory(project, "case", case_id="case", project=project.name, now=when)


def _a_case_that_runs(project: Path) -> None:
    claim_run(project, "case")


def _a_directory_nobody_wrote_an_outcome_in(project: Path) -> None:
    (project / "runs" / "case").mkdir(parents=True)


CLAIMS = [
    pytest.param(
        _a_case_that_runs, None, CaseAliveError, "pulse is fresh", id="a case that runs elsewhere"
    ),
    pytest.param(
        _a_directory_nobody_wrote_an_outcome_in,
        None,
        AttemptClaimedError,
        "claimed",
        id="a claim in flight",
    ),
    pytest.param(
        _a_directory_nobody_wrote_an_outcome_in,
        timedelta(days=2),
        DirectoryWithoutOutcomeError,
        "trash it, or rename it",
        id="a directory without outcome",
    ),
]


@pytest.mark.parametrize(("prepare", "later", "error", "said"), CLAIMS)
def test_a_case_that_cannot_be_claimed_says_why(
    tmp_path: Path,
    prepare: Callable[[Path], None],
    later: timedelta | None,
    error: type[Exception],
    said: str,
) -> None:
    project = tmp_path / "p"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    prepare(project)

    with pytest.raises(error, match=said):
        _claim(project, when=None if later is None else datetime.now(UTC) + later)
