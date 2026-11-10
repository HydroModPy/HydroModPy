"""One seal model for a run and a job, written once and read back by profile."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.document_version import NEWER_REMEDY, OLDER_REMEDY
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.schema.job.seal import JobSeal, read_job_seal
from hydromodpy.schema.seal import (
    SEAL_VERSION,
    ArtifactRecord,
    Seal,
    render_document,
    verify_artifacts,
    write_seal,
)

CORPUS = Path(__file__).parents[2] / "regression" / "frozen_documents" / "v2.0.0" / "current"
JOB_V2 = CORPUS / "chain" / "01-first" / "manifest.json"


def _seal(*, request_id: str = "sha256:abc") -> JobSeal:
    return JobSeal(request_id=request_id, sealed_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_a_job_seal_round_trips_through_its_file(tmp_path: Path):
    target = tmp_path / "manifest.json"
    written = _seal()

    write_seal(target, written)

    read = read_job_seal(target)
    assert read == written
    assert read.manifest_version == SEAL_VERSION == 4
    assert read.profile == "job"


def test_a_job_seal_carries_its_input_set_and_geometry(tmp_path: Path):
    target = tmp_path / "manifest.json"
    written = JobSeal(
        request_id="sha256:abc",
        sealed_at=datetime(2026, 1, 1, tzinfo=UTC),
        inputset={"path": "inputset.json", "id": "sha256:1", "sha256": "2"},
    )

    write_seal(target, written)

    read = read_job_seal(target)
    assert read.inputset is not None and read.inputset.id == "sha256:1"
    assert read.geometry is None


def test_verify_artifacts_accepts_a_matching_file(tmp_path: Path):
    path = tmp_path / "outcome.json"
    path.write_text("{}\n", encoding="utf-8")
    digest, size = sha256_and_size(path)
    seal = Seal(
        profile="job",
        sealed_at=datetime(2026, 1, 1, tzinfo=UTC),
        artifacts=[ArtifactRecord(path="outcome.json", role="document", bytes=size, sha256=digest)],
    )

    assert verify_artifacts(tmp_path, seal) == ()


def test_verify_artifacts_names_a_missing_file(tmp_path: Path):
    seal = Seal(
        profile="job",
        sealed_at=datetime(2026, 1, 1, tzinfo=UTC),
        artifacts=[ArtifactRecord(path="outcome.json", role="document")],
    )

    assert verify_artifacts(tmp_path, seal) == ("outcome.json is sealed and absent",)


def test_verify_artifacts_names_a_changed_file(tmp_path: Path):
    path = tmp_path / "outcome.json"
    path.write_text("{}\n", encoding="utf-8")
    digest, size = sha256_and_size(path)
    path.write_text('{"a": 1}\n', encoding="utf-8")
    seal = Seal(
        profile="job",
        sealed_at=datetime(2026, 1, 1, tzinfo=UTC),
        artifacts=[ArtifactRecord(path="outcome.json", role="document", bytes=size, sha256=digest)],
    )

    problems = verify_artifacts(tmp_path, seal)
    assert len(problems) == 2
    assert all(problem.startswith("outcome.json") for problem in problems)


def test_verify_artifacts_refuses_an_entry_outside_the_directory(tmp_path: Path):
    outside = tmp_path.parent / "elsewhere.json"
    outside.write_text("{}\n", encoding="utf-8")
    seal = Seal(
        profile="job",
        sealed_at=datetime(2026, 1, 1, tzinfo=UTC),
        artifacts=[ArtifactRecord(path="../elsewhere.json", role="output")],
    )

    assert verify_artifacts(tmp_path / "job", seal) == (
        "../elsewhere.json is sealed and lies outside " + str(tmp_path / "job"),
    )


def test_verify_artifacts_reads_a_directory_by_the_tree_digest_the_caller_gives(tmp_path: Path):
    store = tmp_path / "fields.zarr"
    store.mkdir()
    (store / "zarr.json").write_text("{}\n", encoding="utf-8")
    seal = Seal(
        profile="run",
        sealed_at=datetime(2026, 1, 1, tzinfo=UTC),
        artifacts=[ArtifactRecord(path="fields.zarr", role="fields", sha256="abc")],
    )

    assert verify_artifacts(tmp_path, seal, tree_digest=lambda path: "abc") == ()
    assert verify_artifacts(tmp_path, seal, tree_digest=lambda path: "def") == (
        "fields.zarr does not hash to what the seal recorded",
    )
    assert verify_artifacts(tmp_path, seal) == ()


def test_read_job_seal_reads_the_hmp_manifest_v2_of_the_corpus():
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


def test_a_version_4_job_seal_needs_the_job_profile(tmp_path: Path):
    target = tmp_path / "manifest.json"
    target.write_text(
        json.dumps({"manifest_version": 4, "sealed_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionMismatchError, match="profile"):
        read_job_seal(target)


def test_a_run_profile_is_not_read_as_a_job(tmp_path: Path):
    target = tmp_path / "manifest.json"
    target.write_text(
        json.dumps(
            {
                "manifest_version": 4,
                "profile": "run",
                "sealed_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionMismatchError, match="run"):
        read_job_seal(target)


def test_a_newer_manifest_version_is_refused_by_the_version(tmp_path: Path):
    target = tmp_path / "manifest.json"
    target.write_text(
        json.dumps({"manifest_version": 5, "profile": "job"}),
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionMismatchError, match="manifest_version = 5") as refused:
        read_job_seal(target)
    assert NEWER_REMEDY in str(refused.value)


def test_an_older_integer_manifest_version_says_a_pre_release_wrote_it(tmp_path: Path):
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps({"manifest_version": 3, "profile": "job"}), encoding="utf-8")
    with pytest.raises(SchemaVersionMismatchError, match="manifest_version = 3") as refused:
        read_job_seal(target)
    assert OLDER_REMEDY in str(refused.value)


def test_a_seal_is_strict_json_and_refuses_a_number_that_is_not_finite():
    with pytest.raises(ValueError, match="JSON compliant"):
        render_document({"max_abs": float("inf")})


def test_a_document_without_a_version_or_the_v2_schema_is_refused(tmp_path: Path):
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps({"schema": "hmp-manifest/v9"}), encoding="utf-8")
    with pytest.raises(SchemaVersionMismatchError, match="hmp-manifest/v9"):
        read_job_seal(target)


def test_a_json_array_is_no_seal(tmp_path: Path):
    target = tmp_path / "manifest.json"
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(SchemaVersionMismatchError, match="not a JSON object"):
        read_job_seal(target)


def test_a_seal_without_a_profile_or_an_instant_is_refused():
    with pytest.raises(ValidationError, match="profile"):
        Seal.model_validate({"sealed_at": "2026-01-01T00:00:00+00:00"})
    with pytest.raises(ValidationError, match="sealed_at"):
        Seal.model_validate({"profile": "run"})
