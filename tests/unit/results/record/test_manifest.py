"""The seal of a run, version 4: one profile of the common seal, typed on read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.record.manifest import read_seal, seal_problems


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


def test_a_value_key_that_names_no_stored_value_is_refused(tmp_path: Path):
    _write(tmp_path, _payload(values={"rule": "values/1", "digests": {"heads": "abc"}}))

    with pytest.raises(ValueError, match="stored value"):
        read_seal(tmp_path)


def _purged_trial(run_dir: Path, *, kind: str = "trial", mesh_sha256: str | None = None) -> None:
    artifacts = [
        {"path": "fields.zarr", "role": "fields"},
        {"path": "mesh", "role": "mesh", **({"sha256": mesh_sha256} if mesh_sha256 else {})},
    ]
    _write(run_dir, _payload(lineage={"kind": kind}, artifacts=artifacts))


def _write_purged_raw(run_dir: Path, payload: dict) -> None:
    (run_dir / "purged.json").write_text(json.dumps(payload), encoding="utf-8")


PURGED = {
    "schema": "hydromodpy.purged.v1",
    "at": "2026-11-11T08:30:00+00:00",
    "entries": {"fields.zarr": 4096},
}


def test_a_purged_trial_is_complete_without_the_entries_gc_removed(tmp_path: Path):
    _purged_trial(tmp_path)
    (tmp_path / "mesh").mkdir()
    _write_purged_raw(tmp_path, PURGED)

    assert seal_problems(tmp_path) == []


def test_a_witness_on_a_run_that_is_not_a_kept_trial_costs_a_line(tmp_path: Path):
    _purged_trial(tmp_path, kind="promoted")
    (tmp_path / "fields.zarr").mkdir()
    (tmp_path / "mesh").mkdir()
    _write_purged_raw(tmp_path, PURGED)

    assert seal_problems(tmp_path) == ["purged.json: on a run that is not a kept trial"]


def test_a_witness_never_hides_the_loss_of_a_result_run(tmp_path: Path):
    _purged_trial(tmp_path, kind="promoted")
    _write_purged_raw(tmp_path, PURGED)

    problems = seal_problems(tmp_path)

    assert "purged.json: on a run that is not a kept trial" in problems
    assert "fields.zarr is sealed and absent" in problems


def test_a_witness_naming_what_gc_never_removes_costs_a_line(tmp_path: Path):
    _purged_trial(tmp_path)
    (tmp_path / "fields.zarr").mkdir()
    (tmp_path / "mesh").mkdir()
    _write_purged_raw(
        tmp_path,
        {"schema": "hydromodpy.purged.v1", "at": PURGED["at"], "entries": {"tables.parquet": 1}},
    )

    assert seal_problems(tmp_path) == [
        "purged.json: names 'tables.parquet', which gc never removes; gc removes only fields.zarr."
    ]


def test_an_unreadable_witness_costs_a_line(tmp_path: Path):
    _purged_trial(tmp_path)
    (tmp_path / "fields.zarr").mkdir()
    (tmp_path / "mesh").mkdir()
    (tmp_path / "purged.json").write_text("not json", encoding="utf-8")

    problems = seal_problems(tmp_path)

    assert len(problems) == 1 and problems[0].startswith("purged.json: ")


def test_the_mesh_a_purge_keeps_keeps_its_verification(tmp_path: Path):
    _purged_trial(tmp_path, mesh_sha256="0" * 64)
    (tmp_path / "mesh").mkdir()
    _write_purged_raw(tmp_path, PURGED)

    assert seal_problems(tmp_path) == ["mesh does not hash to what the seal recorded"]


def test_the_mesh_folder_is_named_once_by_the_storage_contract():
    from hydromodpy.results.record import manifest
    from hydromodpy.results.storage import contract

    assert manifest.MESH_DIRNAME is contract.MESH_DIRNAME
    assert not hasattr(manifest, "_MESH_DIRNAME")
