"""A plain ``hmp run`` skips a re-run identical to a completed run.

Covers :func:`hydromodpy.project.dispatch.workflow.completed_identical_run`
and :func:`hydromodpy.results.catalog.registration.run_identity_hash`, the
``config_hash`` the catalog records at registration.
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from types import SimpleNamespace

from hydromodpy.project.dispatch.workflow import completed_identical_run
from hydromodpy.results.catalog.registration import run_identity_hash
from tests._helpers.fixtures_catalog import simulation_catalog


def _stub_config(config: dict, root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        model_dump=lambda *, mode="json": config,
        workspace=SimpleNamespace(project_root=str(root)),
    )


def _register(root: Path, config: dict, *, name: str = "demo", status: str = "completed") -> str:
    sid = str(uuid.uuid4())
    with simulation_catalog(root) as cat:
        cat.register_simulation(sid, project="p", solver="modflow6", name=name, config=config)
        cat._backend.execute(
            "UPDATE simulations SET status_id = "
            "(SELECT id FROM statuses WHERE code = ?), "
            "ended_at = current_timestamp WHERE sim_id = ?",
            [status, sid],
        )
    return sid


def _config(sy: float = 0.001, scratch: str = "/p/.hmp/scratch/demo.p111") -> dict:
    return {
        "flow": {"sy": sy},
        "simulation": {"name": "demo"},
        "workspace": {"project_root": "/p", "solver_scratch_folder": scratch},
    }


def test_identical_config_matches_and_change_discriminates(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    sid = _register(root, _config())

    found = completed_identical_run(_stub_config(_config(), root), name="demo")
    assert found == ("demo", sid)

    # Any changed parameter flips the hash, so the run is not a duplicate.
    assert completed_identical_run(_stub_config(_config(sy=0.01), root), name="demo") is None


def test_the_scratch_folder_of_the_process_does_not_count(tmp_path: Path) -> None:
    """Two processes name two scratch folders; the run is the same run."""
    root = tmp_path / "ws"
    sid = _register(root, _config(scratch="/p/.hmp/scratch/demo.p111"))

    other_process = _config(scratch="/p/.hmp/scratch")
    found = completed_identical_run(_stub_config(other_process, root), name="demo")
    assert found is not None
    assert found[1] == sid


def test_another_name_is_another_run(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _register(root, _config())
    assert completed_identical_run(_stub_config(_config(), root), name="other") is None


def test_non_completed_and_trashed_runs_do_not_trigger_skip(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _register(root, _config(), status="running")
    _register(root, _config(), status="trashed")
    assert completed_identical_run(_stub_config(_config(), root), name="demo") is None


def test_missing_catalog_is_fail_open(tmp_path: Path) -> None:
    config = _stub_config(_config(), tmp_path / "absent")
    assert completed_identical_run(config, name="demo") is None


def test_identity_hash_reads_name_and_overrides() -> None:
    config = _config()
    base = run_identity_hash(config, name="demo")
    assert base == run_identity_hash(copy.deepcopy(config), name="demo")
    assert base != run_identity_hash(config, name="demo_k")
    assert base != run_identity_hash(config, name="demo", overrides={"K": 1e-5})
    # The caller's dict is not touched.
    assert config["workspace"]["solver_scratch_folder"].endswith("demo.p111")
    # An override that does not serialise never matches anything.
    odd = {"properties": object()}
    assert run_identity_hash(config, name="demo", overrides=odd) != run_identity_hash(
        config, name="demo", overrides=odd
    )
