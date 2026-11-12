"""Reusing a finished job directory: re-report its outcome or refuse, never write into it.

``job_id`` is a content address, so the same request means the same id. The file
on disk says what the job did and stdout says what this invocation did. They
differ by one member, ``reused``, and by nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import JobUsageError, SchemaVersionMismatchError
from hydromodpy.core.io.document_version import NEWER_REMEDY
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord, now
from hydromodpy.schema.job.reuse import REUSED_MEMBER, reuse_sealed_outcome, reused_outcome_text
from hydromodpy.schema.job.seal import JobSeal
from hydromodpy.schema.seal import write_seal

JOB_ID = "sha256:" + "7" * 64
OTHER_JOB_ID = "sha256:" + "8" * 64
UNREADABLE = "cannot be read as an outcome"


def successful_outcome() -> JobOutcome:
    """A successful outcome with one artifact and one warning."""
    return JobOutcome(
        job_id=JOB_ID,
        process_id="demo-delineate",
        process_version="1.2.3",
        status="successful",
        exit_code=0,
        started_at=now(),
        finished_at=now(),
        outputs=(
            OutputRecord(
                id="watershed_vector",
                path="outputs/watershed.gpkg",
                media_type="application/geopackage+sqlite3",
                bytes=17,
                sha256="a" * 64,
                extra={"hmp:conformsTo": ["GeoParquet-1.1"]},
            ),
        ),
        warnings=("outlet 'north' was not delineated: outside the DEM",),
    )


@pytest.fixture
def sealed(tmp_path: Path) -> JobDirectory:
    job = JobDirectory.create(tmp_path / "job")
    job.request_path.write_text("{}", encoding="utf-8")
    successful_outcome().write(job)
    write_seal(job.manifest_path, JobSeal(sealed_at=now(), request_id=JOB_ID))
    return job


def files_of(job: JobDirectory) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in job.root.iterdir() if path.is_file()}


def test_same_id_returns_the_stored_outcome(sealed: JobDirectory) -> None:
    reused = reuse_sealed_outcome(sealed, job_id=JOB_ID)

    assert reused.reused is True
    assert reused.exit_code == 0
    assert reused.status == "successful"
    assert reused.job_id == JOB_ID


def test_another_id_is_refused(sealed: JobDirectory) -> None:
    with pytest.raises(JobUsageError) as caught:
        reuse_sealed_outcome(sealed, job_id=OTHER_JOB_ID)

    assert JOB_ID in str(caught.value)
    assert OTHER_JOB_ID in str(caught.value)


def test_nothing_is_written(sealed: JobDirectory) -> None:
    before = files_of(sealed)

    reuse_sealed_outcome(sealed, job_id=JOB_ID)
    with pytest.raises(JobUsageError):
        reuse_sealed_outcome(sealed, job_id=OTHER_JOB_ID)

    assert files_of(sealed) == before


# A sealed directory nobody here wrote is a usage error and never a crash.
UNREADABLE_SEALS = [
    pytest.param("{oh dear", "does not read as JSON", id="seal not json"),
    pytest.param("[]", "not a JSON object", id="seal not an object"),
]


@pytest.mark.parametrize(("text", "message"), UNREADABLE_SEALS)
def test_unreadable_seal(sealed: JobDirectory, text: str, message: str) -> None:
    sealed.manifest_path.write_text(text, encoding="utf-8")

    with pytest.raises(SchemaVersionMismatchError, match=message):
        reuse_sealed_outcome(sealed, job_id=JOB_ID)


def test_outcome_of_a_later_version(sealed: JobDirectory) -> None:
    document = read_document(sealed.outcome_path)
    write_document(sealed.outcome_path, {**document, "schema": "hmp-outcome/v2"})

    with pytest.raises(SchemaVersionMismatchError, match=NEWER_REMEDY):
        reuse_sealed_outcome(sealed, job_id=JOB_ID)


def test_outcome_without_a_status(sealed: JobDirectory) -> None:
    document = read_document(sealed.outcome_path)
    del document["status"]
    write_document(sealed.outcome_path, document)

    with pytest.raises(JobUsageError, match=UNREADABLE):
        reuse_sealed_outcome(sealed, job_id=JOB_ID)


def test_status_a_capability_never_writes(sealed: JobDirectory) -> None:
    # "accepted" and "running" describe a job before its process starts. Left to the
    # consistency check alone, "accepted" exiting 130 would be served as a dismissed job.
    document = read_document(sealed.outcome_path)
    write_document(sealed.outcome_path, document | {"status": "accepted", "exit_code": 130})

    with pytest.raises(JobUsageError, match=UNREADABLE):
        reuse_sealed_outcome(sealed, job_id=JOB_ID)


def test_outcome_without_the_reused_member(sealed: JobDirectory) -> None:
    # Merging into a mapping without the member would append a line instead of changing
    # one. Both entry points refuse it.
    document = read_document(sealed.outcome_path)
    del document[REUSED_MEMBER]
    write_document(sealed.outcome_path, document)

    with pytest.raises(JobUsageError, match=UNREADABLE):
        reuse_sealed_outcome(sealed, job_id=JOB_ID)
    with pytest.raises(JobUsageError, match="carries no 'reused' member"):
        reused_outcome_text(sealed)


def test_stdout_text_differs_by_one_member(sealed: JobDirectory) -> None:
    on_disk = sealed.outcome_path.read_text(encoding="utf-8")

    text = reused_outcome_text(sealed)

    assert json.loads(text) == {**json.loads(on_disk), REUSED_MEMBER: True}
    differing = [
        (disk_line, text_line)
        for disk_line, text_line in zip(on_disk.splitlines(), text.splitlines(), strict=True)
        if disk_line != text_line
    ]
    assert len(differing) == 1
    assert f'"{REUSED_MEMBER}"' in differing[0][0]


def test_outcome_file_is_left_alone(sealed: JobDirectory) -> None:
    before = sealed.outcome_path.read_bytes()

    reused_outcome_text(sealed)

    assert sealed.outcome_path.read_bytes() == before
