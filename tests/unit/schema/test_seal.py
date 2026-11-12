"""One seal model for a run and a job, written once and read back by profile."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.schema.job.seal import JobSeal, read_job_seal
from hydromodpy.schema.seal import ArtifactRecord, Seal, render_document, verify_artifacts

CORPUS = Path(__file__).parents[2] / "regression" / "frozen_documents" / "v2.0.0-pre" / "current"
JOB_V2 = CORPUS / "chain" / "01-first" / "manifest.json"


def _seal(*, request_id: str = "sha256:abc") -> JobSeal:
    return JobSeal(request_id=request_id, sealed_at=datetime(2026, 1, 1, tzinfo=UTC))


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


def test_a_seal_is_strict_json_and_refuses_a_number_that_is_not_finite():
    with pytest.raises(ValueError, match="JSON compliant"):
        render_document({"max_abs": float("inf")})


def test_a_document_without_a_version_or_the_v2_schema_is_refused(tmp_path: Path):
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps({"schema": "hmp-manifest/v9"}), encoding="utf-8")
    with pytest.raises(SchemaVersionMismatchError, match="hmp-manifest/v9"):
        read_job_seal(target)
