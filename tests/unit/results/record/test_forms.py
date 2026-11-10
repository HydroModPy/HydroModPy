"""The forms of the 2.0.0, converted in memory when a reader meets them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.record.forms import identity_block, run_seal_v3
from hydromodpy.results.record.manifest import read_manifest, read_seal
from hydromodpy.schema.job.seal import read_job_seal

FROZEN_RUNS = Path(__file__).parents[3] / "regression" / "frozen_runs" / "v2.0.0"
FROZEN_DOCUMENTS = Path(__file__).parents[3] / "regression" / "frozen_documents" / "v2.0.0"
EXPECTED = json.loads((FROZEN_RUNS / "expected.json").read_text(encoding="utf-8"))
DEMO = FROZEN_RUNS / "current" / "projects" / "example" / "runs" / "demo"
CALAGE = FROZEN_RUNS / "current" / "projects" / "example" / "runs" / "calage"
CHAIN = FROZEN_DOCUMENTS / "current" / "chain" / "01-first"
PUBLICATION = FROZEN_DOCUMENTS / "current" / "publication"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            {"manifest_version": 3, "identity": {"config_hash": "x", "sim_id": "s"}},
            {"manifest_version": 4, "profile": "run", "identity": {"sim_id": "s"}},
            id="identity-config-hash-retires",
        ),
        pytest.param(
            {"manifest_version": 3, "config": {"hash": "h", "file": "config.toml"}},
            {
                "manifest_version": 4,
                "profile": "run",
                "config": {"file": "config.toml"},
            },
            id="config-hash-retires",
        ),
        pytest.param(
            {
                "manifest_version": 3,
                "identity": {"config_hash": "x", "sim_id": "s"},
                "config": {"hash": "h", "file": "config.toml"},
            },
            {
                "manifest_version": 4,
                "profile": "run",
                "identity": {"sim_id": "s"},
                "config": {"file": "config.toml"},
            },
            id="both-hashes-retire",
        ),
        pytest.param(
            {
                "manifest_version": 3,
                "artifacts": [
                    {"path": "inputs.json", "role": "other"},
                    {"path": "stray.txt", "role": "other"},
                    {"path": "fields.zarr", "role": "fields"},
                ],
            },
            {
                "manifest_version": 4,
                "profile": "run",
                "artifacts": [
                    {"path": "inputs.json", "role": "inputs"},
                    {"path": "stray.txt", "role": "other"},
                    {"path": "fields.zarr", "role": "fields"},
                ],
            },
            id="inputs-entry-takes-its-role",
        ),
    ],
)
def test_each_manifest_row_converts_a_version_3_seal(payload, expected):
    assert run_seal_v3(payload) == expected


def test_the_identity_row_drops_the_key_that_left():
    assert identity_block({"config_hash": "x", "sim_id": "s"}) == {"sim_id": "s"}


def test_a_block_without_the_key_reads_the_same():
    assert identity_block({"sim_id": "s"}) == {"sim_id": "s"}


@pytest.mark.parametrize(
    ("payload", "request_id", "media_type", "role"),
    [
        pytest.param(
            {
                "schema": "hmp-manifest/v2",
                "job_id": "sha256:job",
                "sealed_at": "2026-01-01T00:00:00Z",
                "artifacts": [{"path": "outcome.json", "mediaType": "application/json"}],
            },
            "sha256:job",
            "application/json",
            "document",
            id="control-document",
        ),
        pytest.param(
            {
                "schema": "hmp-manifest/v2",
                "job_id": "sha256:other",
                "sealed_at": "2026-01-01T00:00:00Z",
                "artifacts": [{"path": "outputs/value.json", "mediaType": "text/plain"}],
            },
            "sha256:other",
            "text/plain",
            "output",
            id="output",
        ),
    ],
)
def test_each_job_row_converts_a_version_2_seal(tmp_path, payload, request_id, media_type, role):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    seal = read_job_seal(path)

    assert seal.request_id == request_id
    assert seal.artifacts[0].media_type == media_type
    assert seal.artifacts[0].role == role
    assert seal.manifest_version == 4 and seal.profile == "job"


@pytest.mark.parametrize(
    ("run_dir", "expected_key"),
    [(DEMO, "demo"), (CALAGE, "calibrated_run")],
)
def test_a_frozen_run_of_the_2_0_0_reads_as_a_version_4_seal(run_dir, expected_key):
    expected = EXPECTED[expected_key]

    seal = read_seal(run_dir)

    assert seal.manifest_version == 4 and seal.profile == "run"
    assert seal.values is None
    assert seal.identity.sim_id == expected["sim_id"]
    assert seal.run.solver == expected["solver"]
    assert seal.run.flow_regime == expected["flow_regime"]
    assert seal.geometry.n_cells == expected["n_cells"]
    assert seal.geometry.n_layers == expected["n_layers"]
    assert seal.period.n_timesteps == expected["n_timesteps"]
    assert seal.checks.budget_pct == pytest.approx(expected["budget_pct"])
    assert "hash" not in seal.config.model_dump()
    assert "config_hash" not in seal.identity.model_dump()


def test_the_retired_key_stays_in_the_manifest_the_file_holds():
    assert "config_hash" in read_manifest(DEMO)["identity"]


def test_the_identity_sidecar_of_the_2_0_0_reads_without_its_hash():
    identity = read_identity_from(DEMO / "exports" / "discharge.csv.meta.json")

    assert identity is not None
    assert identity.sim_id == EXPECTED["demo"]["sim_id"]
    assert identity.solution_key is None and identity.request_id is None
    assert "config_hash" not in identity.model_dump()


def test_the_job_seal_of_the_corpus_reads_its_request_id():
    seal = read_job_seal(CHAIN / "manifest.json")
    outcome = json.loads((CHAIN / "outcome.json").read_text(encoding="utf-8"))

    assert seal.request_id == outcome["job_id"]
    assert all(entry.role in {"document", "output"} for entry in seal.artifacts)


def test_a_published_copy_is_a_version_3_seal_without_values():
    seal = read_seal(PUBLICATION)

    assert seal.manifest_version == 4 and seal.profile == "run"
    assert seal.values is None


REFUSALS = [
    pytest.param({"manifest_version": 1}, SchemaVersionMismatchError, "pre-release", id="v1"),
    pytest.param({"manifest_version": 2}, SchemaVersionMismatchError, "pre-release", id="v2"),
    pytest.param({"run": {}}, SchemaVersionMismatchError, "manifest_version", id="no-version"),
]


@pytest.mark.parametrize(("payload", "error", "sentence"), REFUSALS)
def test_read_seal_refuses_a_form_it_does_not_read(tmp_path, payload, error, sentence):
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(error, match=sentence):
        read_seal(tmp_path)


def test_read_job_seal_refuses_an_unknown_job_schema(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": "hmp-manifest/v1"}), encoding="utf-8")

    with pytest.raises(SchemaVersionMismatchError, match="hmp-manifest/v1"):
        read_job_seal(path)
