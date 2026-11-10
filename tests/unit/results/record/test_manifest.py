"""The seal of a run, version 4: one profile of the common seal, typed on read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.results.record.manifest import (
    MANIFEST_VERSIONS,
    RUN_RECORD_MANIFEST_VERSION,
    list_artifacts,
    read_manifest,
    read_seal,
    seal_problems,
)


def _payload(**overrides):
    payload = {
        "manifest_version": 4,
        "profile": "run",
        "sealed_at": "2026-01-01T00:00:00+00:00",
        "run": {
            "sim_id": "sim",
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
        "geometry": {},
        "period": {},
        "config": {"file": "config.toml", "source": "config.toml"},
        "identity": {
            "case_id": "island",
            "sim_id": "sim",
            "attempt_id": "att",
            "hydromodpy_version": "2.1.0",
            "solution_key": "sha256:solution",
            "request_id": "sha256:request",
            "solver": "modflow6",
        },
        "checks": {},
        "artifacts": [],
    }
    payload.update(overrides)
    return payload


def _write(run_dir: Path, payload: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_the_seal_of_a_run_is_version_four_and_profiles_the_run(tmp_path: Path):
    _write(tmp_path, _payload())

    seal = read_seal(tmp_path)

    assert seal.manifest_version == RUN_RECORD_MANIFEST_VERSION == 4
    assert seal.profile == "run"
    assert MANIFEST_VERSIONS.oldest == 3 and MANIFEST_VERSIONS.current == 4


def test_the_seal_carries_the_digests_of_the_values_under_one_rule(tmp_path: Path):
    _write(
        tmp_path,
        _payload(values={"rule": "values/1", "digests": {"fields/heads": "abc"}}),
    )

    seal = read_seal(tmp_path)

    assert seal.values is not None
    assert seal.values.rule == "values/1"
    assert seal.values.digests == {"fields/heads": "abc"}


def test_a_value_key_that_names_no_stored_value_is_refused(tmp_path: Path):
    _write(tmp_path, _payload(values={"rule": "values/1", "digests": {"heads": "abc"}}))

    with pytest.raises(ValueError, match="stored value"):
        read_seal(tmp_path)


def test_read_manifest_returns_the_file_as_it_is(tmp_path: Path):
    payload = _payload()
    payload["identity"]["config_hash"] = "the 2.0.0 key"
    _write(tmp_path, payload)

    assert read_manifest(tmp_path)["identity"]["config_hash"] == "the 2.0.0 key"


def test_a_version_3_seal_is_migrated_in_memory(tmp_path: Path):
    payload = _payload(manifest_version=3)
    payload.pop("profile")
    payload["config"]["hash"] = "the 2.0.0 hash"
    payload["identity"]["config_hash"] = "the 2.0.0 hash"
    payload["artifacts"] = [{"path": "inputs.json", "role": "other"}]
    _write(tmp_path, payload)

    seal = read_seal(tmp_path)

    assert seal.manifest_version == 4 and seal.profile == "run"
    assert seal.artifacts[0].role == "inputs"
    assert "hash" not in seal.config.model_dump()
    assert "config_hash" not in seal.identity.model_dump()
    assert read_manifest(tmp_path)["identity"]["config_hash"] == "the 2.0.0 hash"


def test_a_pre_release_version_is_refused_by_its_format_version(tmp_path: Path):
    _write(tmp_path, {"manifest_version": 2, "run": {}})

    with pytest.raises(SchemaVersionMismatchError, match="pre-release"):
        read_seal(tmp_path)


def test_a_seal_without_a_version_is_refused(tmp_path: Path):
    _write(tmp_path, {"run": {}})

    with pytest.raises(SchemaVersionMismatchError):
        read_seal(tmp_path)


def test_the_seal_checks_bytes_and_never_recomputes_a_value_digest(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text("[flow]\n", encoding="utf-8")
    digest, size = sha256_and_size(config)
    _write(
        tmp_path,
        _payload(
            artifacts=[
                {
                    "path": "config.toml",
                    "role": "config",
                    "bytes": size,
                    "sha256": digest,
                }
            ],
            values={"rule": "values/1", "digests": {"fields/heads": "not the values"}},
        ),
    )

    assert seal_problems(tmp_path) == []


def test_the_seal_reports_a_changed_artifact(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text("[flow]\n", encoding="utf-8")
    digest, size = sha256_and_size(config)
    _write(
        tmp_path,
        _payload(
            artifacts=[
                {
                    "path": "config.toml",
                    "role": "config",
                    "bytes": size,
                    "sha256": digest,
                }
            ]
        ),
    )
    config.write_text("[flow]\n[other]\n", encoding="utf-8")

    problems = seal_problems(tmp_path)

    assert len(problems) == 2
    assert all(problem.startswith("config.toml") for problem in problems)


def test_an_entry_the_roles_do_not_name_stays_other(tmp_path: Path):
    (tmp_path / "stray.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "fields.zarr").mkdir()
    (tmp_path / "tables.parquet").mkdir()
    (tmp_path / "tables.parquet" / "simulation.parquet").write_bytes(b"")

    roles = {entry["path"]: entry["role"] for entry in list_artifacts(tmp_path)}

    assert roles["stray.txt"] == "other"
    assert roles["fields.zarr"] == "fields"
    assert roles["tables.parquet/simulation.parquet"] == "table:simulation"


def test_the_mesh_folder_is_named_once_by_the_storage_contract():
    from hydromodpy.results.record import manifest
    from hydromodpy.results.storage import contract

    assert manifest.MESH_DIRNAME is contract.MESH_DIRNAME
    assert not hasattr(manifest, "_MESH_DIRNAME")
