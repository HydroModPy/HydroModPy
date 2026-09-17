"""``manifest.json`` exists if and only if the job finished, and its absence
is never ambiguous.

Everything an orchestrator decides — this job is done, these bytes are the
ones it produced, this input set is the one it consumed — rests on that
sentence. So the seal is refused here whenever a document of the write order
is missing or an output the outcome claims is not on disk, and re-reading a
sealed directory catches a file that changed after the fact.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.inputset import InputSet, Licence, build_inputset, file_resource
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord, now
from hydromodpy.schema.job.seal import seal_job, verify_job

JOB_ID = "sha256:" + "2" * 64


def _job_with_outputs(tmp_path: Path) -> tuple[JobDirectory, InputSet, tuple[OutputRecord, ...]]:
    """A job that ran: one input read, one artefact written."""
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
    digest, size = sha256_file(produced)
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


def _write_the_three_documents(
    job: JobDirectory, inputset: InputSet, outputs: tuple[OutputRecord, ...]
) -> None:
    write_document(job.inputset_path, inputset.to_document())
    write_document(job.provenance_path, {"schema": "hmp-provenance/v1", "tool": "hydromodpy"})
    started = now()
    JobOutcome(
        job_id=JOB_ID,
        process_id="demo-delineate",
        process_version="1.2.3",
        status="successful",
        exit_code=0,
        started_at=started,
        finished_at=now(),
        outputs=outputs,
    ).write(job)


def _sealed(tmp_path: Path) -> JobDirectory:
    job, inputset, outputs = _job_with_outputs(tmp_path)
    _write_the_three_documents(job, inputset, outputs)
    seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=outputs)
    return job


def test_a_sealed_job_inventories_its_outputs_and_its_documents(tmp_path: Path) -> None:
    job = _sealed(tmp_path)
    manifest = read_document(job.manifest_path)

    assert manifest["schema"] == "hmp-manifest/v2"
    assert manifest["profile"] == "job"
    assert manifest["job_id"] == JOB_ID
    assert {entry["path"] for entry in manifest["artifacts"]} == {
        "outputs/watershed.gpkg",
        "inputset.json",
        "provenance.json",
        "outcome.json",
    }


def test_the_seal_carries_nothing_that_lives_in_another_document(tmp_path: Path) -> None:
    """Tampering with the outcome must break the seal, not produce a disagreement."""
    manifest = read_document(_sealed(tmp_path).manifest_path)

    for absent in ("status", "exit_code", "duration_s", "started_at", "errors", "warnings"):
        assert absent not in manifest


def test_the_seal_points_at_the_input_set_by_id_and_by_digest(tmp_path: Path) -> None:
    job = _sealed(tmp_path)
    manifest = read_document(job.manifest_path)
    inputset = read_document(job.inputset_path)

    assert manifest["inputset"]["id"] == inputset["id"]
    assert manifest["inputset"]["sha256"] == sha256_file(job.inputset_path)[0]


def test_a_job_whose_documents_are_not_written_yet_is_not_sealed(tmp_path: Path) -> None:
    job, inputset, outputs = _job_with_outputs(tmp_path)

    with pytest.raises(ValueError, match="not written yet"):
        seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=outputs)

    assert not job.is_sealed


def test_a_job_claiming_an_output_that_is_not_there_is_not_sealed(tmp_path: Path) -> None:
    job, inputset, outputs = _job_with_outputs(tmp_path)
    _write_the_three_documents(job, inputset, outputs)
    job.resolve_output("outputs/watershed.gpkg").unlink()

    with pytest.raises(ValueError, match="not on disk"):
        seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=outputs)

    assert not job.is_sealed


def test_the_seal_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    job = _sealed(tmp_path)

    assert [entry.name for entry in job.root.glob("*.tmp-*")] == []


def test_two_outputs_on_one_path_are_not_sealed(tmp_path: Path) -> None:
    """A seal that inventories one file twice describes neither."""
    job, inputset, outputs = _job_with_outputs(tmp_path)
    _write_the_three_documents(job, inputset, outputs)
    twice = (*outputs, outputs[0])

    with pytest.raises(ValueError, match="two outputs claim"):
        seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=twice)

    assert not job.is_sealed


def test_a_control_document_is_hashed_from_the_disk_and_not_from_a_record(tmp_path: Path) -> None:
    """A capability may declare ``outcome.json`` among its outputs.

    Its record was necessarily built before that file existed, so a seal built
    from the record would carry a digest of nothing. The bytes at seal time win.
    """
    job, inputset, outputs = _job_with_outputs(tmp_path)
    _write_the_three_documents(job, inputset, outputs)
    stale = OutputRecord(
        id="outcome",
        path="outcome.json",
        media_type="application/json",
        bytes=0,
        sha256="f" * 64,
    )

    seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=(*outputs, stale))

    sealed = {entry["path"]: entry for entry in read_document(job.manifest_path)["artifacts"]}
    assert sealed["outcome.json"]["sha256"] == sha256_file(job.outcome_path)[0]
    assert verify_job(job).ok


def test_a_sealed_job_verifies_against_its_own_seal(tmp_path: Path) -> None:
    report = verify_job(_sealed(tmp_path))

    assert report.ok
    assert report.problems == ()


def test_an_unsealed_job_is_reported_unsealed_and_not_broken(tmp_path: Path) -> None:
    job, _, _ = _job_with_outputs(tmp_path)

    report = verify_job(job)

    assert report.sealed is False
    assert report.ok is False


def test_an_output_rewritten_after_the_seal_is_caught(tmp_path: Path) -> None:
    job = _sealed(tmp_path)
    job.resolve_output("outputs/watershed.gpkg").write_bytes(b"something else entirely")

    report = verify_job(job)

    assert not report.ok
    assert any("does not hash" in problem for problem in report.problems)


def test_an_output_removed_after_the_seal_is_caught(tmp_path: Path) -> None:
    job = _sealed(tmp_path)
    job.resolve_output("outputs/watershed.gpkg").unlink()

    report = verify_job(job)

    assert any("sealed and absent" in problem for problem in report.problems)


def test_a_licence_rewritten_after_the_seal_is_caught(tmp_path: Path) -> None:
    """The reason the id digests the complete resource array."""
    job = _sealed(tmp_path)
    inputset = read_document(job.inputset_path)
    inputset["resources"][0]["licence"]["spdx"] = "CC0-1.0"
    write_document(job.inputset_path, inputset)

    report = verify_job(job)

    assert not report.ok
    assert any("digests to" in problem for problem in report.problems)


def test_an_outcome_from_another_job_is_caught(tmp_path: Path) -> None:
    job = _sealed(tmp_path)
    outcome = read_document(job.outcome_path)
    outcome["job_id"] = "sha256:" + "9" * 64
    write_document(job.outcome_path, outcome)

    report = verify_job(job)

    assert any("job id" in problem for problem in report.problems)


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ('["not", "an", "object"]', "not a JSON object"),
        ("{", "cannot be read as JSON"),
        ('{"artifacts": "outputs/watershed.gpkg"}', "no artifact list"),
        ('{"artifacts": [{"bytes": 3}]}', "carries no path"),
        ('{"artifacts": [{"path": "../../etc/passwd", "sha256": "x"}]}', "outside the job"),
    ],
)
def test_a_manifest_this_process_did_not_write_is_reported_and_not_raised(
    tmp_path: Path, manifest: str, expected: str
) -> None:
    """A verification verb is pointed at directories it did not write."""
    job = _sealed(tmp_path)
    job.manifest_path.write_text(manifest, encoding="utf-8")

    report = verify_job(job)

    assert not report.ok
    assert any(expected in problem for problem in report.problems)


def test_an_inputset_this_process_did_not_write_is_reported_and_not_raised(
    tmp_path: Path,
) -> None:
    job = _sealed(tmp_path)
    job.inputset_path.write_text("[]", encoding="utf-8")

    report = verify_job(job)

    assert not report.ok
    assert any("not a JSON object" in problem for problem in report.problems)


def test_eight_writers_of_one_document_leave_one_whole_document(tmp_path: Path) -> None:
    """The temporary name is a uuid, so two writers never share it."""
    job = JobDirectory.create(tmp_path / "job_4714")
    payloads = [{"writer": index} for index in range(8)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda payload: write_document(job.outcome_path, payload), payloads))

    assert read_document(job.outcome_path) in payloads
    assert [entry.name for entry in job.root.glob("*.tmp-*")] == []
