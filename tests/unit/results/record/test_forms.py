"""The forms of a pre-release, converted in memory when a reader meets them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.record.forms import run_seal_v3
from hydromodpy.results.record.manifest import read_manifest, read_seal
from hydromodpy.schema.job.seal import read_job_seal

FROZEN_RUNS = Path(__file__).parents[3] / "regression" / "frozen_runs" / "v2.0.0"
FROZEN_DOCUMENTS = Path(__file__).parents[3] / "regression" / "frozen_documents" / "v2.0.0-pre"
EXPECTED = json.loads((FROZEN_RUNS / "expected.json").read_text(encoding="utf-8"))
DEMO = FROZEN_RUNS / "current" / "projects" / "example" / "runs" / "demo"
CALAGE = FROZEN_RUNS / "current" / "projects" / "example" / "runs" / "calage"
CHAIN = FROZEN_DOCUMENTS / "current" / "chain" / "01-first"
PUBLICATION = FROZEN_DOCUMENTS / "current" / "publication"


def pre_release(run_dir: Path, tmp_path: Path) -> Path:
    """Copy the manifest and the export sidecar of *run_dir* in the form 2.0.0rc1 wrote."""
    out = tmp_path / run_dir.name
    sidecar = run_dir / "exports" / "discharge.csv.meta.json"
    (out / "exports").mkdir(parents=True)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(manifest_version=3, config={**manifest["config"], "hash": "x"})
    del manifest["values"], manifest["profile"]
    documents = [(out / "manifest.json", manifest)]
    if sidecar.is_file():
        documents.append((out / "exports" / sidecar.name, json.loads(sidecar.read_text("utf-8"))))
    for path, document in documents:
        identity = document.get("identity", {})
        for key in ("solution_key", "request_id", "solver"):
            identity.pop(key, None)
        identity["config_hash"] = "x"
        path.write_text(json.dumps(document), encoding="utf-8")
    return out


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


@pytest.mark.parametrize(
    ("run_dir", "expected_key"),
    [(DEMO, "demo"), (CALAGE, "calibrated_run")],
)
def test_a_frozen_run_of_a_pre_release_reads_as_a_version_4_seal(run_dir, expected_key, tmp_path):
    expected = EXPECTED[expected_key]

    seal = read_seal(pre_release(run_dir, tmp_path))

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


def test_the_retired_key_stays_in_the_manifest_the_file_holds(tmp_path):
    assert "config_hash" in read_manifest(pre_release(DEMO, tmp_path))["identity"]


def test_the_identity_sidecar_of_a_pre_release_reads_without_its_hash(tmp_path):
    identity = read_identity_from(
        pre_release(DEMO, tmp_path) / "exports" / "discharge.csv.meta.json"
    )

    assert identity is not None
    assert identity.sim_id == EXPECTED["demo"]["sim_id"]
    assert identity.solution_key is None and identity.request_id is None
    assert "config_hash" not in identity.model_dump()


def test_the_job_seal_of_the_corpus_reads_its_request_id():
    seal = read_job_seal(CHAIN / "manifest.json")
    outcome = json.loads((CHAIN / "outcome.json").read_text(encoding="utf-8"))

    assert seal.request_id == outcome["job_id"]
    assert all(entry.role in {"document", "output"} for entry in seal.artifacts)


REFUSALS = [
    pytest.param({"manifest_version": 1}, SchemaVersionMismatchError, "pre-release", id="v1"),
    pytest.param({"manifest_version": 2}, SchemaVersionMismatchError, "pre-release", id="v2"),
    pytest.param({"run": {}}, SchemaVersionMismatchError, "manifest_version", id="no-version"),
]
