"""Sealing a job directory and verifying it again.

``manifest.json`` exists if and only if the job finished, so its absence is never
ambiguous. The seal is refused when a document of the write order is missing or
when an output the outcome claims is not on disk. Verification catches a file
that changed after the seal and reports a manifest it did not write.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.inputset import InputSet, Licence, build_inputset, file_resource
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord, now
from hydromodpy.schema.job.seal import read_job_seal, seal_job, verify_job

JOB_ID = "sha256:" + "2" * 64
CORPUS = Path(__file__).parents[3] / "regression" / "frozen_documents" / "v2.0.0-pre" / "current"
JOB_V2 = CORPUS / "chain" / "01-first" / "manifest.json"


def job_with_outputs(tmp_path: Path) -> tuple[JobDirectory, InputSet, tuple[OutputRecord, ...]]:
    """A job that ran, with one input read and one artifact written."""
    job = JobDirectory.create(tmp_path / "job_4711")
    job.ensure_workspace()
    job.request_path.write_text("{}", encoding="utf-8")

    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"II*\x00" * 64)
    inputset = build_inputset(
        [
            file_resource(
                "dem",
                role="dem",
                path=dem,
                media_type="image/tiff; application=geotiff",
                licence=Licence(spdx="etalab-2.0", confidence="assumed"),
            )
        ]
    )

    produced = job.outputs_dir / "watershed.gpkg"
    produced.write_bytes(b"SQLite format 3\x00")
    digest, size = sha256_and_size(produced)
    outputs = (
        OutputRecord(
            id="watershed_vector",
            path="outputs/watershed.gpkg",
            media_type="application/geopackage+sqlite3",
            bytes=size,
            sha256=digest,
        ),
    )
    return job, inputset, outputs


def write_the_three_documents(
    job: JobDirectory, inputset: InputSet, outputs: tuple[OutputRecord, ...]
) -> None:
    write_document(job.inputset_path, inputset.to_document())
    write_document(job.provenance_path, {"schema": "hmp-provenance/v1", "tool": "hydromodpy"})
    JobOutcome(
        job_id=JOB_ID,
        process_id="demo-delineate",
        process_version="1.2.3",
        status="successful",
        exit_code=0,
        started_at=now(),
        finished_at=now(),
        outputs=outputs,
    ).write(job)


def sealed_job(tmp_path: Path) -> JobDirectory:
    job, inputset, outputs = job_with_outputs(tmp_path)
    write_the_three_documents(job, inputset, outputs)
    seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=outputs)
    return job


def test_documents_not_written_yet(tmp_path: Path) -> None:
    job, inputset, outputs = job_with_outputs(tmp_path)

    with pytest.raises(ValueError, match="not written yet"):
        seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=outputs)
    assert not job.is_sealed


def test_output_not_on_disk(tmp_path: Path) -> None:
    job, inputset, outputs = job_with_outputs(tmp_path)
    write_the_three_documents(job, inputset, outputs)
    job.resolve_output("outputs/watershed.gpkg").unlink()

    with pytest.raises(ValueError, match="not on disk"):
        seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=outputs)
    assert not job.is_sealed


def test_two_outputs_on_one_path(tmp_path: Path) -> None:
    # A seal that inventories one file twice describes neither.
    job, inputset, outputs = job_with_outputs(tmp_path)
    write_the_three_documents(job, inputset, outputs)

    with pytest.raises(ValueError, match="two outputs claim"):
        seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=(*outputs, outputs[0]))
    assert not job.is_sealed


def test_unsealed_job_is_not_broken(tmp_path: Path) -> None:
    job, _, _ = job_with_outputs(tmp_path)

    report = verify_job(job)

    assert report.sealed is False
    assert report.ok is False


def test_licence_rewritten_after_the_seal(tmp_path: Path) -> None:
    # The id digests the complete resource array, so this change must show.
    job = sealed_job(tmp_path)
    inputset = read_document(job.inputset_path)
    inputset["resources"][0]["licence"]["spdx"] = "CC0-1.0"
    write_document(job.inputset_path, inputset)

    report = verify_job(job)

    assert not report.ok
    assert any("digests to" in problem for problem in report.problems)


def test_outcome_from_another_job(tmp_path: Path) -> None:
    job = sealed_job(tmp_path)
    outcome = read_document(job.outcome_path)
    outcome["job_id"] = "sha256:" + "9" * 64
    write_document(job.outcome_path, outcome)

    assert any("request id" in problem for problem in verify_job(job).problems)


def test_sealed_entry_outside_the_job(tmp_path: Path) -> None:
    job = sealed_job(tmp_path)
    manifest = read_document(job.manifest_path)
    manifest["artifacts"][0]["path"] = "../../etc/passwd"
    job.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert any("lies outside" in problem for problem in verify_job(job).problems)


# A verification verb is pointed at directories it did not write, so it reports and does not raise.
FOREIGN_MANIFESTS = [
    pytest.param('["not", "an", "object"]', "not a JSON object", id="array"),
    pytest.param("{", "does not read as JSON", id="not json"),
    pytest.param('{"artifacts": []}', "carries no manifest_version", id="no version"),
    pytest.param('{"manifest_version": 3}', "manifest_version = 4", id="old version"),
    pytest.param('{"manifest_version": 4, "profile": "run"}', "profiles 'run'", id="run profile"),
    pytest.param(
        '{"manifest_version": 4, "profile": "job", "artifacts": "outputs/watershed.gpkg"}',
        "valid list",
        id="artifacts not a list",
    ),
]


@pytest.mark.parametrize(("manifest", "expected"), FOREIGN_MANIFESTS)
def test_foreign_manifest_is_reported(tmp_path: Path, manifest: str, expected: str) -> None:
    job = sealed_job(tmp_path)
    job.manifest_path.write_text(manifest, encoding="utf-8")

    report = verify_job(job)

    assert not report.ok
    assert any(expected in problem for problem in report.problems)


def test_foreign_inputset_is_reported(tmp_path: Path) -> None:
    job = sealed_job(tmp_path)
    job.inputset_path.write_text("[]", encoding="utf-8")

    report = verify_job(job)

    assert not report.ok
    assert any("not a JSON object" in problem for problem in report.problems)


def test_read_job_seal_of_the_corpus() -> None:
    seal = read_job_seal(JOB_V2)

    assert (
        seal.request_id == "sha256:9c243fccb904e0e46747009d961f07f4d24d42757e6fcc317d1df8d0ff7929bd"
    )
    assert seal.profile == "job" and seal.manifest_version == 4
    assert seal.artifacts[0].media_type == "application/json"
    assert [entry.role for entry in seal.artifacts] == [
        "output",
        "document",
        "document",
        "document",
    ]


# (document, the part of the message that names the fix)
UNREADABLE_SEALS = [
    pytest.param(
        {"manifest_version": 4, "sealed_at": "2026-01-01T00:00:00+00:00"},
        "profile",
        id="no profile",
    ),
    pytest.param({"schema": "hmp-manifest/v9"}, "hmp-manifest/v9", id="unknown schema"),
]


@pytest.mark.parametrize(("document", "message"), UNREADABLE_SEALS)
def test_read_job_seal_refusals(tmp_path: Path, document: dict, message: str) -> None:
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SchemaVersionMismatchError, match=message):
        read_job_seal(target)
